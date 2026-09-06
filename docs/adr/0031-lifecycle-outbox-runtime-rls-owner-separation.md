# ADR 0031: Lifecycle Outbox Runtime RLS Owner Separation

- Status: Proposed
- Date: 2026-09-06

## Context

ADR 0002 requires shared lifecycle-outbox access to use PostgreSQL row-level security with `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`, and excludes `SUPERUSER` and `BYPASSRLS` application identities. Migration 0009 independently verifies the canonical relation and policy catalogs after migration convergence. Runtime must still re-prove live role authority because `SET ROLE`, post-migration grants, ownership changes, or operator DDL can change what one connection can do while a process remains alive.

Earlier repairs established that a normal `NOSUPERUSER NOBYPASSRLS` role is still unsafe when it owns the outbox, can exercise or administer the owner role, or holds `TRUNCATE`, `DELETE`, table/column `REFERENCES`, `TRIGGER`, or any table/column `UPDATE` authority. `TRUNCATE` bypasses row filtering, `DELETE` can erase tenant-local durable publication intent, `UPDATE` can rewrite committed evidence, `REFERENCES` can introduce external dependencies, and `TRIGGER` can attach executable relation programs. Those are distinct from cross-tenant RLS bypass and are all outside the package runtime contract.

The UPDATE repair also removed `SELECT ... FOR UPDATE` from replay coordination. PostgreSQL requires `UPDATE` privilege for a locking `SELECT`, which made the intended least-privilege role inconsistent because the package otherwise needs only `SELECT` and `INSERT`. Package writers now serialize same-tenant/same-event adjudication through a transaction-level advisory lock before an ordinary tenant-qualified `SELECT`.

Fresh review found a separate role-identity gap. `_require_rls_application_role()` inspected only effective `CURRENT_USER`. PostgreSQL documents that after `SET ROLE`, ordinary permission checks use `CURRENT_USER`, but permission to execute later `SET ROLE` commands continues to be evaluated against the current session user (`SESSION_USER`). A login role can therefore authenticate, `SET ROLE` to an apparently safe application role, pass a CURRENT_USER-only admission query, and still retain the ability to select an outbox-owner or other unsafe role later in the same session. The previous positive-control smoke itself authenticated as `postgres` and then selected a safe role, which demonstrated why an effective-role-only assertion cannot establish the package's claimed separation boundary.

The relevant authority is not the DSN username string. It is the live PostgreSQL role closure: the effective role, the session role, and every role that `SESSION_USER` can currently select through `SET ROLE` or can make selectable through `ADMIN OPTION`. If any such role is superuser, `BYPASSRLS`, the outbox owner, can exercise/administer the owner, or carries destructive/mutating/programming authority on the outbox, the connection is outside the supported runtime boundary.

PostgreSQL also permits an initially authenticated superuser to change `SESSION_USER` with `SET SESSION AUTHORIZATION` and later reset it to the original identity. PostgreSQL does not expose that original database-role identity through `SESSION_USER` after such a change. This package therefore does not treat an admin-originated connection that hides its initial authority through `SET SESSION AUTHORIZATION` as a supported runtime deployment. Runtime connections must originate from a non-administrative login identity whose live session/set-role closure satisfies this ADR.

## Constraints

- Keep the caller-owned transaction seam and transaction-local tenant GUC.
- Preserve same-tenant/same-event serialization across package writers.
- Do not parse DSN usernames as authorization evidence; inspect live PostgreSQL role/catalog authority.
- Re-prove both effective `CURRENT_USER` and the authority reachable/administerable from `SESSION_USER` before tenant binding or outbox data SQL.
- Do not claim to detect an original superuser after that superuser deliberately changes session authorization; such admin-originated sessions are outside the supported runtime deployment boundary.
- Do not rerun migration 0009 on every read/write.
- Do not grant mutation authority merely to obtain a coordination lock.
- Do not reject inert role-membership edges when neither inherited `USAGE`, `SET`, nor admin authority is exercisable.
- Runtime authority must remain sufficient for the actual package SQL: `SELECT` and `INSERT`, with no ambient or selectable/administerable `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER` on the outbox.
- Coordination identity must not expose tenant or evidence content in logs or errors.
- A coordination-key collision may serialize unrelated work but must not admit incorrect durable state.

## Decision

`_require_rls_application_role()` keeps one fail-closed catalog round trip. It first resolves the canonical outbox relation and requires RLS to remain enabled and forced. It then evaluates the role closure that can still affect the connection:

- effective `CURRENT_USER`;
- authenticated/current session identity `SESSION_USER`;
- every role for which `SESSION_USER` has `SET` authority; and
- every role for which `SESSION_USER` holds `MEMBER WITH ADMIN OPTION`, because that authority can change membership options and manufacture later `SET ROLE` access.

The connection is rejected if any role in that closure:

- is `SUPERUSER` or `BYPASSRLS`;
- owns `public.llm_context_lifecycle_outbox`;
- can exercise, select, or administer the owner role through `USAGE`, `SET`, or `MEMBER WITH ADMIN OPTION`;
- has `TRUNCATE` or `DELETE` table privilege;
- has any table-level or column-level `UPDATE` privilege;
- has any table-level or column-level `REFERENCES` privilege; or
- has `TRIGGER` privilege.

This permits a least-privilege login wrapper to `SET ROLE` to a separate runtime role when both identities and every selectable/administerable role remain inside the same append-only authority envelope. It rejects a superficially safe `CURRENT_USER` when the authenticated session can later become the owner or another unsafe role without reconnecting.

The package continues to use transaction-level `pg_catalog.pg_advisory_xact_lock(bigint)` for serialized replay reads. The bigint key is a deterministic signed 64-bit projection of SHA-256 over the already-validated local tenant scope, a NUL separator, and evidence ID. The digest is coordination metadata only, not durable identity or authorization evidence. A collision can create excess serialization; durable identity remains `(tenant_scope, evidence_id)` plus exact row revalidation.

All security-critical system functions and relations remain schema-qualified. Any absent or malformed authority verdict fails before tenant GUC binding or durable-row SQL.

## Alternatives considered

### Inspect only `CURRENT_USER`

Rejected. PostgreSQL explicitly evaluates `SET ROLE` permission against the session user, not the role currently selected with `SET ROLE`. Effective-role-only checks therefore cannot prove that the same connection lacks a later owner/destructive role escape.

### Inspect only `CURRENT_USER` and `SESSION_USER`

Rejected. A safe login role can hold `SET TRUE` membership in another role without inheriting that role's privileges. Direct privilege checks on `SESSION_USER` alone can therefore remain false even though the login can select an unsafe role later. Admission must inspect selectable/administerable role closure, not just two role records.

### Reject every role-membership edge

Rejected. PostgreSQL 16+ permits inert membership with `INHERIT FALSE, SET FALSE` and no admin option. The package rejects exercisable or self-enablable unsafe authority rather than membership existence.

### Permit an admin login that immediately `SET ROLE`s to the runtime role

Rejected for the supported runtime boundary. A superuser session can select arbitrary roles and can later regain administrative authority. A temporary effective-role downgrade is not equivalent to least-privilege connection authority.

### Attempt to infer the original authenticated database role from DSN or `system_user`

Rejected. DSN text is caller/configuration input, not live authorization evidence. `system_user` reports authentication method/identity and can be `NULL` under trust authentication or differ from a database role under authentication mappings. Deployment must instead originate runtime connections from a least-privilege PostgreSQL login and retain that separation operationally.

### Keep `SELECT ... FOR UPDATE` and allow minimal column `UPDATE`

Rejected. PostgreSQL requires `UPDATE` for locking `SELECT`, and any granted update column is itself mutable durable authority. Every canonical outbox column participates in identity, lifecycle meaning, provenance, or operational evidence.

### Remove locking entirely and rely only on UNIQUE

Rejected. UNIQUE prevents two durable rows for one replay key, but the package deliberately provides serialized compare/adjudication semantics for a caller-owned transaction. Removing coordination would widen the concurrency contract unnecessarily.

### Use a session-level advisory lock

Rejected. Session locks outlive the caller transaction unless explicitly released and are harder to make failure-safe through pooled connections. `pg_advisory_xact_lock` matches aggregate transaction ownership.

### Rerun migration 0009 on every runtime operation

Rejected. Installer/final-admission verification is substantially broader than the hot role check and does not prove the connection's current role-selection authority.

## Verification and promotion

Retained lineage for owner/RLS and destructive/programming authority includes:

- owner-separation RED `f60522ca0ba33733110cdef0d46736e0d9e6edf7`, real PostgreSQL specimen `ac8e780a751d2233f54b6e441081de8ecc85860d`, and repair `86411b4fb28e4429ebb966a87423ae810b91eb3b`;
- membership-semantics refinement `0ad858a9b9cbc3329f1ff0f1de2f65c7385d85e0` with positive inert-membership control `ec51cc12f986a295dde2936971f5f47057eebcc5`;
- `TRUNCATE`/`REFERENCES`/`TRIGGER` RED `75693be1dff5e16ba4ccb02da546ad799342a9f2`, executable specimen `ef03358df4b1830a3c2bd7a5b96e2e686348fe30`, and repair `86db8aa93e877186819e4698ac43bff6ba9be582`;
- append-only `DELETE` RED `513686c89e9922f7b536494ec3f126cfd14a06c1`, executable specimen `68079570fced0010ff3771706bb632e5f761728b`, and repair `6bef0692451cb0a512bb587a2f392c27ead65c4b`;
- UPDATE/coordination static RED `f5208b7b124248eae1e9855ec771734abe0e3ffb`, realistic PostgreSQL specimen `638dac99442cd4fcb00c9e63cb97b1c695bfea3e`, and causal repair `b354a569c1bb3857be33cf65612c9260c2a77f8e`.

Fresh authenticated-session lineage is:

- RED `d3d19da69af08d05eb6c4f7589003161c51a6988` adds a static contract requiring `SESSION_USER` role-closure inspection and a PostgreSQL/container specimen with a non-superuser login that can `SET ROLE` to both a safe runtime role and the outbox owner;
- causal production repair `89114ce0c6fb7cc27b03f492e8f4fe37693f2195` evaluates both effective/session identities plus every session-selectable/administerable role before tenant/data SQL;
- unit contract repair `41c74ca599e744aff67407dc883975708cba76df` aligns the existing role-authority assertions with the new closure semantics.

The realistic PostgreSQL specimen is wired into the container acceptance lane. It has not earned hosted GREEN until the exact final repaired head executes successfully. Keep this ADR Proposed until exact-head repository quality gates and the PostgreSQL acceptance specimen are terminal successful.

## Consequences

The supported lifecycle-outbox connection is now an append-only RLS subject at both effective and session authority levels. A deployment may use a separate least-privilege login wrapper plus runtime role, but the login must not retain or be able to manufacture access to an unsafe role. Maintenance, retention/erasure, relation programming, schema ownership, and administrative login authority stay on separate connections/identities.

This closes a connection-local authority escape without broadening the domain model or changing durable schema. It adds catalog work proportional to the PostgreSQL role set because admission evaluates the session's selectable/administerable role closure. No p95 latency claim is made until an exact-head performance lane measures the resulting hot-path query under realistic role cardinality.

## References

PostgreSQL Global Development Group. (2026a). *SET ROLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026b). *System information functions and operators*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026c). *Role membership*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026d). *GRANT*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026e). *SET SESSION AUTHORIZATION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-session-authorization.html

PostgreSQL Global Development Group. (2026f). *System administration functions: Advisory lock functions*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026g). *Row security policies*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html
