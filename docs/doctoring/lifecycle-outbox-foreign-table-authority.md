# Lifecycle outbox foreign-table authority

Status: current Draft-stack security evidence. The protected branch is not changed by this document until the owning stack is normally integrated.

## Problem

The lifecycle outbox is isolated with forced PostgreSQL RLS, but local relation privileges are not a complete description of read authority once a runtime role can reach a foreign table. `postgres_fdw` resolves a local user through a user mapping and executes against the referenced remote table under the mapped remote identity. PostgreSQL documents that after a foreign server, user mapping, and foreign table are configured, selecting the foreign table accesses the underlying remote data. The local catalog therefore cannot establish that the remote identity, remote RLS policy, remote ownership, or future remote configuration preserves this package's tenant invariant.

Hosted CI on exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c` provided the reality RED. CI run `34077132444`, PostgreSQL/container job `101605370280`, created a loopback `postgres_fdw` mapping from an ordinary local runtime role to a distinct remote role with `BYPASSRLS`. Direct access to `public.llm_context_lifecycle_outbox` under `tenant-a` returned only the tenant row, while the selectable foreign relation returned both seeded tenants. The same authority was reachable through an ordinary outer view whose owner, rather than the runtime caller, held the foreign-table `SELECT` privilege. Production admission accepted both paths and the smoke failed with `runtime admitted a directly selectable foreign table whose user mapping reaches lifecycle rows under BYPASSRLS remote authority`.

## Decision

Runtime admission treats a user-schema foreign table (`pg_class.relkind = 'f'`) as an opaque authority boundary when it is reachable by the effective/authenticated runtime role or through the existing ordinary-view execution closure. Admission fails before tenant binding and before lifecycle row SQL.

The implementation deliberately does not parse `postgres_fdw` connection options, user-mapping options, remote role names, remote table names, or remote RLS state. Those are remote mutable authority and may not even describe a PostgreSQL server for another FDW. A local allowlist would therefore manufacture assurance the package cannot prove. Workloads that require foreign-data access must separate that authority from the lifecycle-outbox runtime role/connection rather than combine it with this forced-RLS credential.

This is conservative by design: a selectable foreign table that is unrelated to the outbox still prevents admission because the package cannot prove the remote target remains unrelated over the lifetime of the credential. That operational restriction is preferable to silently treating mutable remote identity as local RLS evidence.

## Verification contract

- `tests/smoke_context_lifecycle_outbox_foreign_table_authority.sh` is the executable PostgreSQL specimen. It proves the cross-tenant result first, then requires fail-closed package admission for the direct and view-hidden paths.
- `tests/test_context_lifecycle_outbox_foreign_table_authority.py` pins both direct `relkind = 'f'` discovery and ordinary-view traversal into a foreign relation.
- Existing ordinary-view, materialized-view, `SECURITY DEFINER`, role-admin, RLS-policy, DML, and replay-arbiter smokes remain required; this control does not replace them.
- Exact-head GREEN may be claimed only when the unchanged production head passes the hosted PostgreSQL/container specimen and the repository's full CI/Release Acceptance gates.

## Consequences and follow-up

The live admission query now scans one more relation kind in the existing catalog graph. Issue #307 remains the performance owner: buyer acceptance must include this admission cost in connection-to-cleanup p50/p95/p99 measurements and may not exclude security catalog work to meet the p95 target. If the catalog graph becomes a measurable hot path, optimize the query/provenance model without weakening the foreign-authority invariant.

## Primary evidence

PostgreSQL Global Development Group. (n.d.). *postgres_fdw — access data stored in external PostgreSQL servers*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/postgres-fdw.html

PostgreSQL Global Development Group. (n.d.). *CREATE USER MAPPING*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createusermapping.html

PostgreSQL Global Development Group. (n.d.). *pg_class*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/catalog-pg-class.html
