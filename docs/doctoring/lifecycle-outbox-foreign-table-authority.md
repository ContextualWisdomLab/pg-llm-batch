# Lifecycle outbox foreign-table authority

Status: current Draft-stack security evidence. The protected branch is not changed by this document until the owning stack is normally integrated.

## Problem

The lifecycle outbox is isolated with forced PostgreSQL RLS, but local relation privileges are not a complete description of read authority once a runtime role can reach a foreign table. `postgres_fdw` resolves a local user through a user mapping and executes against the referenced remote table under the mapped remote identity. PostgreSQL documents that after a foreign server, user mapping, and foreign table are configured, selecting the foreign table accesses the underlying remote data. The local catalog therefore cannot establish that the remote identity, remote RLS policy, remote ownership, or future remote configuration preserves this package's tenant invariant.

Hosted CI on exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c` provided the first reality RED. CI run `34077132444`, PostgreSQL/container job `101605370280`, created a loopback `postgres_fdw` mapping from an ordinary local runtime role to a distinct remote role with `BYPASSRLS`. Direct access to `public.llm_context_lifecycle_outbox` under `tenant-a` returned only the tenant row, while the selectable foreign relation returned both seeded tenants. The same authority was reachable through an ordinary outer view whose owner, rather than the runtime caller, held the foreign-table `SELECT` privilege. Production admission accepted the direct path and the smoke failed with `runtime admitted a directly selectable foreign table whose user mapping reaches lifecycle rows under BYPASSRLS remote authority`.

Reviewing that repair exposed a second mechanism before declaring completion. A foreign relation can be read while a materialized view is populated, after which the runtime reads copied rows without contacting the foreign server again. A caller therefore does not need current `SELECT` on the foreign table to retain remote cross-tenant data: it needs only `SELECT` on the materialized copy. Static RED `2c3a6a58cc6a8613c9ad5630693caa81d69a29be` and executable RED `9479d11d8141cc799d4ae671e1d852efb97442d1` preserve this copied-foreign-data path separately from direct/view-mediated execution.

## Decision

Runtime admission treats a user-schema foreign table (`pg_class.relkind = 'f'`) as an opaque authority boundary when it is reachable by the effective/authenticated runtime role, through the existing ordinary-view execution closure, or as definition provenance of a reachable materialized relation. Admission fails before tenant binding and before lifecycle row SQL.

The materialized provenance rule is intentionally source-based. If a runtime-readable materialized view's cycle-safe definition provenance contains a foreign relation, the copy is rejected even when the caller cannot select that foreign relation and even after the remote read has completed. Current copied contents, a tenant literal in the defining query, and the authority used during the most recent refresh are not durable proofs of tenant isolation.

The implementation deliberately does not parse `postgres_fdw` connection options, user-mapping options, remote role names, remote table names, or remote RLS state. Those are remote mutable authority and may not even describe a PostgreSQL server for another FDW. A local allowlist would therefore manufacture assurance the package cannot prove. Workloads that require foreign-data access must separate that authority from the lifecycle-outbox runtime role/connection rather than combine it with this forced-RLS credential.

This is conservative by design: directly reachable foreign data and materialized copies sourced from foreign data are rejected even when they appear unrelated to the outbox, because the package cannot prove that the remote target remains unrelated over the lifetime of the credential or copied relation. That operational restriction is preferable to silently treating mutable remote identity or copied remote rows as local RLS evidence.

## Verification contract

- `tests/smoke_context_lifecycle_outbox_foreign_table_authority.sh` is the executable PostgreSQL specimen. It proves the cross-tenant remote result first, then requires fail-closed package admission for direct foreign access, a caller-readable materialized copy sourced from the foreign relation, and a view-hidden foreign path. The final positive control removes those authorities and requires ordinary tenant-local load to succeed.
- `tests/test_context_lifecycle_outbox_foreign_table_authority.py` pins direct `relkind = 'f'` discovery, ordinary-view traversal into a foreign relation, and foreign-source detection inside materialized provenance.
- Existing ordinary-view, local materialized-outbox, `SECURITY DEFINER`, role-admin, RLS-policy, DML, and replay-arbiter smokes remain required; this control does not replace them.
- Exact-head GREEN may be claimed only when the unchanged production head passes the hosted PostgreSQL/container specimen and the repository's full CI/Release Acceptance gates.

## Consequences and follow-up

The live admission query now scans one more relation kind in the existing catalog graph and inspects the relation kind of materialized-definition sources. Issue #307 remains the performance owner: buyer acceptance must include this admission cost in connection-to-cleanup p50/p95/p99 measurements and may not exclude security catalog work to meet the p95 target. If the catalog graph becomes a measurable hot path, optimize the query/provenance model without weakening the foreign-authority invariant.

## Primary evidence

PostgreSQL Global Development Group. (n.d.). *postgres_fdw — access data stored in external PostgreSQL servers*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/postgres-fdw.html

PostgreSQL Global Development Group. (n.d.). *CREATE USER MAPPING*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createusermapping.html

PostgreSQL Global Development Group. (n.d.). *pg_class*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/catalog-pg-class.html
