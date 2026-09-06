# ADR 0031: Lifecycle Outbox Runtime RLS Owner Separation

- Status: Proposed
- Date: 2026-09-06

## Context

ADR 0002 requires shared lifecycle-outbox access to use PostgreSQL row-level security with `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. Migration 0009 independently verifies the canonical relation and policy catalogs after migration convergence. Runtime must still re-prove live role authority because `SET ROLE`, post-migration grants, ownership changes, role-attribute changes, or operator DDL can change what one connection can do while a process remains alive.

Earlier repairs established that a normal runtime role is unsafe when it owns the outbox, can exercise or administer the owner role, or holds `TRUNCATE`, `DELETE`, table/column `REFERENCES`, `TRIGGER`, or any table/column `UPDATE` authority. `TRUNCATE` is outside row filtering, `DELETE` can erase tenant-local durable publication intent, `UPDATE` can rewrite committed evidence, `REFERENCES` can introduce external dependencies, and `TRIGGER` can attach executable relation programs. Those are distinct from cross-tenant RLS bypass and are all outside the package runtime contract.

The UPDATE repair also removed `SELECT ... FOR UPDATE` from replay coordination. PostgreSQL requires `UPDATE` privilege for a locking `SELECT`, which made the intended least-privilege role inconsistent because the package otherwise needs only `SELECT` and `INSERT`. Package writers now serialize same-tenant/same-event adjudication through a transaction-level advisory lock before an ordinary tenant-qualified `SELECT`.

A later review found that effective `CURRENT_USER` alone is not sufficient. PostgreSQL evaluates later `SET ROLE` permission against `SESSION_USER`, so a login can select an apparently safe role and still retain a path to an owner or otherwise unsafe role. Runtime admission therefore evaluates the effective role, session role, roles selectable by the session identity, and roles whose membership the session identity can administer.

The same live boundary includes the canonical RLS policy itself. Migration 0009 is point-in-time installer evidence: a table owner can later replace the policy under the same name while leaving both relation RLS flags enabled. Runtime therefore checks the sole canonical policy identity, command and role scope, permissive mode, parser-normalized `USING`/`WITH CHECK` expressions, and reviewed catalog dependencies before it binds tenant state or touches durable rows.

Fresh review found one additional authority class missing from that closure: PostgreSQL `REPLICATION`. A `REPLICATION` role can initiate replication connections and create or drop replication slots; PostgreSQL describes it as a very highly privileged role that should only be used for replication. That attribute is not ordinary outbox DML authority and is not, by itself, asserted here to bypass RLS: publisher row-security policies can still execute for a non-superuser replication role without `BYPASSRLS`. The product boundary is narrower and clearer: a tenant application connection that needs only `SELECT` and `INSERT` must not co-locate cluster-level replication connection/slot authority. Replication identities belong to a separate operator boundary.

PostgreSQL also permits an initially authenticated superuser to change `SESSION_USER` with `SET SESSION AUTHORIZATION` and later reset it. The package cannot recover a deliberately hidden original database-role identity from the post-change session state. Admin-originated or replication-originated sessions that downgrade after connection establishment are therefore outside the supported runtime deployment boundary.

## Constraints

- Keep the caller-owned transaction seam and transaction-local tenant GUC.
- Preserve same-tenant/same-event serialization across package writers.
- Do not parse DSN usernames as authorization evidence; inspect live PostgreSQL role/catalog authority.
- Re-prove effective `CURRENT_USER`, authenticated `SESSION_USER`, and every session-selectable/administerable role before tenant binding or outbox data SQL.
- Require the entire admitted closure to remain `NOSUPERUSER NOREPLICATION NOBYPASSRLS` and outside outbox owner/destructive/programming authority.
- Re-prove the sole canonical RLS policy's live identity, command, role scope, permissive mode, `USING`, `WITH CHECK`, and reviewed catalog dependencies in the same runtime admission round trip.
- Do not claim to detect an original administrator or replication identity after deliberate session-authorization downgrade; such sessions are unsupported.
- Do not rerun migration 0009 on every read/write.
- Do not grant mutation authority merely to obtain a coordination lock.
- Do not reject inert role-membership edges when neither inherited `USAGE`, `SET`, nor admin authority is exercisable.
- Runtime authority must remain sufficient for the actual package SQL: `SELECT` and `INSERT`, with no ambient or selectable/administerable `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER` on the outbox.
- Coordination identity must not expose tenant or evidence content in logs or errors.
- A coordination-key collision may serialize unrelated work but must not admit incorrect durable state.

## Decision

`_require_rls_application_role()` keeps one fail-closed catalog round trip. It resolves the canonical outbox relation and requires RLS to remain enabled and forced. In that same query it requires exactly one policy on the relation and requires that policy to remain the canonical `plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2` definition: `ALL` commands, permissive mode, `PUBLIC`, and parser-normalized `USING` and `WITH CHECK` predicates equal to `tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)`. Normal expression dependencies are restricted to the reviewed PostgreSQL `current_setting(text,bool)` function and text equality operator, matching migration 0009's final-admission contract. Policy drift is rejected; runtime never repairs owner DDL silently.

The same round trip evaluates the role closure that can still affect the connection:

- effective `CURRENT_USER`;
- authenticated/current session identity `SESSION_USER`;
- every role for which `SESSION_USER` has `SET` authority; and
- every role for which `SESSION_USER` holds `MEMBER WITH ADMIN OPTION`, because that authority can manufacture later `SET ROLE` access.

The connection is rejected if any role in that closure:

- is `SUPERUSER`, `REPLICATION`, or `BYPASSRLS`;
- owns `public.llm_context_lifecycle_outbox`;
- can exercise, select, or administer the owner role through `USAGE`, `SET`, or `MEMBER WITH ADMIN OPTION`;
- has `TRUNCATE` or `DELETE` table privilege;
- has any table-level or column-level `UPDATE` privilege;
- has any table-level or column-level `REFERENCES` privilege; or
- has `TRIGGER` privilege.

This permits a least-privilege login wrapper to `SET ROLE` to a separate runtime role when both identities and every selectable/administerable role remain inside the same append-only authority envelope. It rejects a superficially safe effective role when the authenticated session can later become an owner, replication role, or another unsafe role without reconnecting.

The package continues to use transaction-level `pg_catalog.pg_advisory_xact_lock(bigint)` for serialized replay reads. The bigint key is a deterministic signed 64-bit projection of SHA-256 over the already-validated local tenant scope, a NUL separator, and evidence ID. The digest is coordination metadata only, not durable identity or authorization evidence. A collision can create excess serialization; durable identity remains `(tenant_scope, evidence_id)` plus exact row revalidation.

All security-critical system functions and relations remain schema-qualified. Any absent or malformed authority or policy verdict fails before tenant GUC binding or durable-row SQL.

## Alternatives considered

### Inspect only `CURRENT_USER`

Rejected. PostgreSQL evaluates `SET ROLE` permission against the session user, not merely the role currently selected with `SET ROLE`. Effective-role-only checks cannot prove that the connection lacks a later owner/destructive role escape.

### Inspect only `CURRENT_USER` and `SESSION_USER`

Rejected. A safe login can hold selectable membership in another role without inheriting that role's privileges. Direct checks on the two active role records can therefore remain safe while a later `SET ROLE` path is unsafe.

### Allow `REPLICATION` because ordinary SQL still uses RLS

Rejected. The decision does not rely on a claim that `REPLICATION` automatically bypasses RLS. PostgreSQL separately grants replication-mode connection and replication-slot authority to such roles and calls the attribute very highly privileged. A tenant runtime connection has no product requirement for that cluster-level authority, so co-location violates least privilege and the operator/runtime bounded-context split.

### Trust migration 0009 as continuing RLS policy authority

Rejected. Migration 0009 proves the catalog at its own transaction boundary. Policy owner DDL after migration can preserve the policy name and both relation RLS flags while replacing the actual `USING`/`WITH CHECK` semantics.

### Check only policy name and RLS flags

Rejected. PostgreSQL policy names identify catalog objects per table, not semantic content. The command scope, target roles, permissive/restrictive mode and both policy expression trees determine which rows are visible or writable.

### Reject every role-membership edge

Rejected. PostgreSQL 16+ permits inert membership with no inherited, selectable, or admin authority. The package rejects exercisable or self-enablable unsafe authority rather than membership existence.

### Permit an administrator or replication login that immediately `SET ROLE`s to runtime

Rejected for the supported runtime boundary. A temporary effective-role downgrade is not equivalent to a least-privilege connection identity, and the package cannot prove a deliberately hidden original session authority after `SET SESSION AUTHORIZATION` changes it.

### Keep `SELECT ... FOR UPDATE` and allow minimal column `UPDATE`

Rejected. PostgreSQL requires `UPDATE` for locking `SELECT`, and any granted update column is itself mutable durable authority. Every canonical outbox column participates in identity, lifecycle meaning, provenance, or operational evidence.

### Remove locking entirely and rely only on UNIQUE

Rejected. UNIQUE prevents two durable rows for one replay key, but the package deliberately provides serialized compare/adjudication semantics for a caller-owned transaction.

### Use a session-level advisory lock

Rejected. Session locks outlive the caller transaction unless explicitly released and are harder to make failure-safe through pooled connections. `pg_advisory_xact_lock` matches aggregate transaction ownership.

### Rerun migration 0009 on every runtime operation

Rejected. Installer/final-admission verification is substantially broader than the hot runtime check. Runtime reuses only the live relation/policy and connection-authority evidence needed to prove the application boundary.

## Verification and promotion

Retained lineage for owner/RLS and destructive/programming authority includes:

- owner-separation RED `f60522ca0ba33733110cdef0d46736e0d9e6edf7`, PostgreSQL specimen `ac8e780a751d2233f54b6e441081de8ecc85860d`, and repair `86411b4fb28e4429ebb966a87423ae810b91eb3b`;
- membership refinement `0ad858a9b9cbc3329f1ff0f1de2f65c7385d85e0` with inert-membership control `ec51cc12f986a295dde2936971f5f47057eebcc5`;
- `TRUNCATE`/`REFERENCES`/`TRIGGER` RED `75693be1dff5e16ba4ccb02da546ad799342a9f2`, PostgreSQL specimen `ef03358df4b1830a3c2bd7a5b96e2e686348fe30`, and repair `86db8aa93e877186819e4698ac43bff6ba9be582`;
- append-only `DELETE` RED `513686c89e9922f7b536494ec3f126cfd14a06c1`, PostgreSQL specimen `68079570fced0010ff3771706bb632e5f761728b`, and repair `6bef0692451cb0a512bb587a2f392c27ead65c4b`;
- UPDATE/coordination RED `f5208b7b124248eae1e9855ec771734abe0e3ffb`, PostgreSQL specimen `638dac99442cd4fcb00c9e63cb97b1c695bfea3e`, and repair `b354a569c1bb3857be33cf65612c9260c2a77f8e`.

Authenticated-session lineage is:

- RED `d3d19da69af08d05eb6c4f7589003161c51a6988` adds a static contract and PostgreSQL specimen for a non-superuser login that can `SET ROLE` to both a safe runtime role and the outbox owner;
- causal repair `89114ce0c6fb7cc27b03f492e8f4fe37693f2195` evaluates effective/session identities plus every session-selectable/administerable role before tenant/data SQL;
- unit contract repair `41c74ca599e744aff67407dc883975708cba76df` aligns role-authority assertions with the closure semantics.

Live policy-authority lineage is:

- static RED `645d655e2cca11c89e0fa7bcd50fac9f52f1898e` requires runtime admission to prove exact canonical `pg_policy` semantics;
- PostgreSQL RED specimen `5309b8f5631ae1d4570bfb0fed9b21839b88d923` replaces the canonical policy under the same name and demonstrates cross-tenant visibility before repair;
- CI wiring `c99f9a17624df8610d259ffec0276a6add9bdaba` puts that specimen in the PostgreSQL/container lane;
- causal repair `434e7a5c269dc9780b9160580683d7467ece3565` adds the exact live policy proof before tenant binding or outbox DML.

Replication-authority lineage is:

- static RED `52e22ab3fd2824efa7fc0b9ada5f8cd3f0626b8b` requires `rolreplication` to be part of the live role-closure admission contract;
- PostgreSQL/container RED specimen `9879fcf1ee0aea9c5eb91d1f1021c9f0efe15487` creates a `LOGIN NOSUPERUSER NOBYPASSRLS REPLICATION` runtime principal with only outbox `SELECT, INSERT` and requires fail-closed admission rather than co-locating replication authority;
- causal production repair `555d9ebfdd407f7d6b5f6805338c9da236d2a309` rejects `rolreplication` anywhere in the effective/session-selectable/administerable closure.

The realistic PostgreSQL specimens are wired into the container acceptance lane. They have not earned hosted GREEN until the exact final repaired head executes successfully. Keep this ADR Proposed until exact-head repository quality gates and PostgreSQL acceptance are terminal successful.

## Consequences

The supported lifecycle-outbox connection is an append-only RLS subject at both effective and session authority levels, and the tenant filter itself is a live runtime invariant rather than a migration-history assumption. A deployment may use a separate least-privilege login wrapper plus runtime role, but neither that login nor any selectable/administerable role may carry owner, destructive/programming, superuser, replication, or RLS-bypass authority. Maintenance, retention/erasure, relation programming, policy ownership, schema ownership, replication, and administrative authority stay on separate connections/identities.

This closes connection-local role escape, same-name policy drift, and replication-authority co-location without broadening the domain model or changing durable schema. It adds catalog work proportional to the PostgreSQL role set plus one bounded policy/dependency lookup inside the same round trip. No p95 latency claim is made until an exact-head performance lane measures the hot-path query under realistic role cardinality.

## References

PostgreSQL Global Development Group. (2026a). *SET ROLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (2026b). *System information functions and operators*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026c). *Role membership*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (2026d). *GRANT*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-grant.html

PostgreSQL Global Development Group. (2026e). *SET SESSION AUTHORIZATION*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-set-session-authorization.html

PostgreSQL Global Development Group. (2026f). *System administration functions: Advisory lock functions*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026g). *Row security policies*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026h). *pg_policy*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026i). *CREATE ROLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createrole.html

PostgreSQL Global Development Group. (2026j). *pg_roles*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/view-pg-roles.html
