# ADR 0031: Lifecycle Outbox Runtime RLS Owner Separation

- Status: Proposed
- Date: 2026-09-06

## Context

ADR 0002 requires shared lifecycle-outbox access to use PostgreSQL row-level security with `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`, and excludes `SUPERUSER` and `BYPASSRLS` application identities. Migration 0009 independently verifies the canonical relation and policy catalogs after migration convergence. Runtime must still re-prove the effective application role because `SET ROLE`, post-migration grants, ownership changes, or operator DDL can change authority while a process remains alive.

Earlier repairs on this decision established that a normal `NOSUPERUSER NOBYPASSRLS` role is still unsafe when it owns the outbox, can exercise or administer the owner role, or holds `TRUNCATE`, `DELETE`, table/column `REFERENCES`, or `TRIGGER`. `TRUNCATE` bypasses row filtering, `DELETE` can erase tenant-local durable publication intent, `REFERENCES` can introduce external dependencies, and `TRIGGER` can attach executable relation programs. Those are distinct from cross-tenant RLS bypass and are all outside the package runtime contract.

Fresh review found the remaining DML authority gap. The runtime still preserved `UPDATE` solely because `load_in_transaction(..., for_update=True)` used `SELECT ... FOR UPDATE`. PostgreSQL requires `UPDATE` privilege for a locking `SELECT`, but that same privilege independently permits a tenant role to mutate any granted outbox column that RLS allows it to see. Column-level `UPDATE (event_type)`, for example, can rewrite committed lifecycle evidence in place while the other tenant remains invisible. This violates the append-only replay/conflict invariant even though RLS itself is working correctly.

The previous design also made the intended least-privilege role inconsistent: the realistic runtime role was granted only `SELECT, INSERT`, while enqueue preflight required `SELECT ... FOR UPDATE`. The lock mechanism, rather than the durable model, was forcing a privilege the model must forbid.

## Constraints

- Keep the caller-owned transaction seam and transaction-local tenant GUC.
- Preserve same-tenant/same-event serialization across package writers.
- Do not parse DSN usernames as authorization evidence; `CURRENT_USER` after `SET ROLE` is the relevant role.
- Do not rerun migration 0009 on every read/write.
- Do not grant mutation authority merely to obtain a coordination lock.
- Do not reject inert role-membership edges when neither inherited `USAGE`, `SET`, nor admin authority is exercisable.
- Runtime authority must remain sufficient for the actual package SQL: `SELECT` and `INSERT`, with no ambient `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER` on the outbox.
- Coordination identity must not expose tenant or evidence content in logs or errors.
- A coordination-key collision may serialize unrelated work but must not admit incorrect durable state.

## Decision

`_require_rls_application_role()` keeps one fail-closed catalog round trip and admits runtime access only when all of the following are simultaneously true:

- effective `CURRENT_USER` is neither superuser nor `BYPASSRLS`;
- the canonical outbox still has RLS enabled and forced;
- `CURRENT_USER` is not the relation owner and cannot exercise, select, or self-grant the owner role through `USAGE`, `SET`, or `MEMBER WITH ADMIN OPTION`;
- `CURRENT_USER` has no `TRUNCATE` or `DELETE` table privilege;
- `CURRENT_USER` has no table-level or column-level `UPDATE` privilege, checked with `has_any_column_privilege(..., 'UPDATE')`;
- `CURRENT_USER` has no table-level or column-level `REFERENCES` privilege; and
- `CURRENT_USER` has no `TRIGGER` privilege.

The package removes row-lock coupling from replay serialization. `load_in_transaction(..., for_update=True)` keeps its compatibility parameter name, but a true value now acquires a transaction-level PostgreSQL advisory lock with `pg_advisory_xact_lock(bigint)` before the plain tenant-qualified `SELECT`. The bigint key is a deterministic signed 64-bit projection of SHA-256 over the already-validated local tenant scope, a NUL separator, and evidence ID. The digest is used only to choose a coordination key, not as durable identity or a cryptographic authorization decision. A 64-bit collision can only create excess serialization because durable identity remains the `(tenant_scope, evidence_id)` UNIQUE key and the full row is revalidated.

Transaction-level advisory locking preserves the required critical section without giving the application role data-mutation authority. Package writers for the same tenant/event identity serialize before the existence check and retain the lock through insert/replay adjudication until the caller-owned transaction ends. Direct SQL writers that do not participate in advisory locking remain bounded by the canonical UNIQUE constraint and `ON CONFLICT DO NOTHING`; the package's conflict path re-reads durable state before deciding exact replay versus conflict.

The relation and all security-critical system functions remain schema-qualified. Any missing/malformed authority verdict fails before tenant GUC binding or durable-row SQL.

## Alternatives considered

### Keep `SELECT ... FOR UPDATE` and allow minimal column `UPDATE`

Rejected. PostgreSQL explicitly requires `UPDATE` for locking `SELECT`, and any granted update column is itself mutable durable authority. Choosing an allegedly harmless column merely moves the integrity hole: every canonical outbox column participates in identity, lifecycle meaning, provenance, or operational evidence.

### Permit `UPDATE` because RLS still filters it

Rejected. RLS prevents cross-tenant mutation but does not make mutation of committed evidence inside the authorized tenant compatible with an append-only outbox. The defect is durable-integrity loss, not RLS bypass.

### Remove locking entirely and rely only on UNIQUE

Rejected. UNIQUE prevents two durable rows for one replay key, but the package deliberately provides serialized compare/adjudication semantics for a caller-owned transaction. Removing coordination would widen the concurrency contract unnecessarily.

### Use a session-level advisory lock

Rejected. Session locks outlive the caller transaction unless explicitly released and are harder to make failure-safe through pooled connections. `pg_advisory_xact_lock` is scoped to the current transaction and therefore matches aggregate transaction ownership.

### Use Python's built-in `hash()` as the advisory key

Rejected. Python hash randomization is process-local and not stable across workers. A deterministic digest projection gives every process the same PostgreSQL bigint for the same validated identity.

### Reject every role-membership edge

Rejected. PostgreSQL 16+ can retain membership while both inherited usage and `SET ROLE` are disabled. Runtime checks exercisable owner authority rather than membership existence.

### Rerun migration 0009 on every runtime operation

Rejected. Installer/final-admission verification is substantially broader than the hot effective-role check and does not replace proof of the current role's grants.

## Verification and promotion

Retained lineage for owner/RLS and destructive/programming authority includes:

- owner-separation RED `f60522ca0ba33733110cdef0d46736e0d9e6edf7`, real PostgreSQL specimen `ac8e780a751d2233f54b6e441081de8ecc85860d`, and repair `86411b4fb28e4429ebb966a87423ae810b91eb3b`;
- membership-semantics refinement `0ad858a9b9cbc3329f1ff0f1de2f65c7385d85e0` with positive inert-membership control `ec51cc12f986a295dde2936971f5f47057eebcc5`;
- `TRUNCATE`/`REFERENCES`/`TRIGGER` RED `75693be1dff5e16ba4ccb02da546ad799342a9f2`, executable specimen `ef03358df4b1830a3c2bd7a5b96e2e686348fe30`, and repair `86db8aa93e877186819e4698ac43bff6ba9be582`;
- append-only `DELETE` RED `513686c89e9922f7b536494ec3f126cfd14a06c1`, executable specimen `68079570fced0010ff3771706bb632e5f761728b`, and repair `6bef0692451cb0a512bb587a2f392c27ead65c4b`.

Fresh UPDATE/coordination lineage is:

- static RED `f5208b7b124248eae1e9855ec771734abe0e3ffb` requires effective-role admission to reject any-column `UPDATE`;
- realistic PostgreSQL RED specimen `638dac99442cd4fcb00c9e63cb97b1c695bfea3e` grants only `UPDATE (event_type)` to an ordinary forced-RLS tenant role, mutates that tenant's committed event while preserving the other tenant, and also requires a `SELECT, INSERT`-only safe role to enqueue successfully;
- causal production repair `b354a569c1bb3857be33cf65612c9260c2a77f8e` rejects UPDATE and replaces row locking with deterministic transaction advisory locking, with unit/fake-cursor contracts aligned in the same commit.

The PostgreSQL specimen is committed to the container acceptance lane. It is not hosted GREEN until the exact final repaired head executes it successfully. Keep this ADR Proposed until exact-head repository quality gates and realistic PostgreSQL acceptance are terminal successful.

## Consequences

The supported lifecycle-outbox runtime role is now a true append-only RLS subject: it needs `SELECT` and `INSERT` for the package path and must not hold `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER`. Maintenance, retention/erasure, relation programming, and schema ownership stay with separate operator identities.

Replay serialization is now an application-defined transaction advisory lock rather than a row update lock. This removes an unnecessary privilege from the hot path while preserving one-transaction atomicity. Hash collisions can increase contention but cannot merge durable identities or bypass the canonical UNIQUE/revalidation contract.

The hot path still performs the existing role/catalog query and now performs one advisory-lock SQL statement only on serialized (`for_update=True`) reads. No p95 latency claim is made until the exact-head performance lane measures it.

## References

PostgreSQL Global Development Group. (2026a). *Privileges*. In *PostgreSQL 16 documentation*. https://www.postgresql.org/docs/16/ddl-priv.html

PostgreSQL Global Development Group. (2026b). *SELECT*. In *PostgreSQL 16 documentation*. https://www.postgresql.org/docs/16/sql-select.html

PostgreSQL Global Development Group. (2026c). *System administration functions: Advisory lock functions*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026d). *Row security policies*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026e). *Role membership*. In *PostgreSQL 16 documentation*. https://www.postgresql.org/docs/16/role-membership.html
