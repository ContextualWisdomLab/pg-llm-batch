# Lifecycle outbox foreign-table authority

Status: current Draft-stack security evidence. The protected branch is not changed by this document until the owning stack is normally integrated.

## Problem

The lifecycle outbox is isolated with forced PostgreSQL RLS, but local relation privileges are not a complete description of read authority once a runtime role can reach foreign data. `postgres_fdw` resolves a local user through a user mapping and executes against the referenced remote table under the mapped remote identity. PostgreSQL documents that after a foreign server, user mapping, and foreign table are configured, selecting the foreign table accesses the underlying remote data. The local catalog therefore cannot establish that the remote identity, remote RLS policy, remote ownership, or future remote configuration preserves this package's tenant invariant.

Hosted CI on exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c` provided the first reality RED. CI run `34077132444`, PostgreSQL/container job `101605370280`, created a loopback `postgres_fdw` mapping from an ordinary local runtime role to a distinct remote role with `BYPASSRLS`. Direct access to `public.llm_context_lifecycle_outbox` under `tenant-a` returned only the tenant row, while the selectable foreign relation returned both seeded tenants. The same authority was reachable through an ordinary outer view whose owner, rather than the runtime caller, held the foreign-table `SELECT` privilege. Production admission accepted the direct path.

Reviewing that repair exposed a second mechanism. A foreign relation can be read while a materialized view is populated, after which the runtime reads copied rows without contacting the foreign server again. A caller therefore does not need current `SELECT` on the foreign table to retain remote cross-tenant data: it needs only `SELECT` on the materialized copy. Static RED `2c3a6a58cc6a8613c9ad5630693caa81d69a29be` and executable RED `9479d11d8141cc799d4ae671e1d852efb97442d1` preserve this copied-foreign-data path separately from direct/view-mediated execution.

A third mechanism is parent-mediated access. PostgreSQL 18 states that inherited queries check permissions on the named parent table, while rows from children participate in the query under the parent's row-security policies. Foreign tables may participate in inheritance hierarchies, and declarative partitions may themselves be foreign tables. Exact RED `be5e0abe55586b6e23a867e9c05a9845133310bc` made that concrete in hosted PostgreSQL. The runtime had `SELECT` on a partitioned parent and no direct `SELECT` on its foreign default partition; the local forced-RLS outbox returned one tenant row, but selecting the parent returned both remote rows through the caller's user mapping. CI `34081839661` failed in PostgreSQL/container job `101618458532` at the new partitioned-foreign authority smoke, while all preceding runtime smokes succeeded.

## Decision

Runtime admission treats foreign data (`pg_class.relkind = 'f'`) as an opaque authority boundary when it is reachable by the effective/authenticated runtime role directly, through ordinary-view execution, through an ordinary or partitioned inheritance parent, or as definition provenance of a reachable materialized relation. Admission fails before tenant binding and before lifecycle row SQL.

The implementation builds `foreign_inheritance_ancestor(relation_oid)` as a cycle-safe recursive closure that starts from every foreign relation and walks upward through `pg_inherits`. A user-schema ordinary or partitioned parent is admitted into the reachable relation graph only when the closure shows a foreign descendant; a caller-readable parent then fails closed even if the foreign child has no caller ACL. Ordinary views preserve their existing effective-principal semantics while gaining the same parent-aware reachability.

The materialized provenance rule is source-based. If a runtime-readable materialized view's cycle-safe definition provenance contains the lifecycle outbox, a foreign relation, or an ordinary/partitioned parent with any foreign descendant, the copy is rejected even when the caller cannot select the foreign source and even after the remote read has completed. Current copied contents, a tenant literal in the defining query, partition bounds, child ACL absence, and the authority used during the most recent refresh are not durable proofs of tenant isolation.

The implementation deliberately does not parse `postgres_fdw` connection options, user-mapping options, remote role names, remote table names, remote RLS state, or partition constraints. Those are remote or mutable authority and may not even describe a PostgreSQL server for another FDW. A local allowlist would therefore manufacture assurance the package cannot prove. Workloads that require foreign-data access must separate that authority from the lifecycle-outbox runtime role/connection rather than combine it with this forced-RLS credential.

This is conservative by design: directly reachable foreign data, foreign-bearing inheritance parents, and materialized copies sourced from either are rejected even when they appear unrelated to the outbox, because the package cannot prove that the remote target remains unrelated over the lifetime of the credential or copied relation. That operational restriction is preferable to silently treating mutable remote identity, parent-only ACLs, or copied remote rows as local RLS evidence.

## Verification contract

- `tests/smoke_context_lifecycle_outbox_foreign_table_authority.sh` proves the cross-tenant remote result first, then requires fail-closed package admission for direct foreign access, a caller-readable materialized copy sourced from the foreign relation, and a view-hidden foreign path. Its final positive control removes those authorities and requires ordinary tenant-local load to succeed.
- `tests/smoke_context_lifecycle_outbox_partitioned_foreign_authority.sh` is the inheritance reality specimen added at RED `be5e0abe55586b6e23a867e9c05a9845133310bc`. It grants only parent `SELECT`, proves child `SELECT` is absent, proves the parent still returns both mapped remote tenants, and requires package admission to reject the parent-mediated authority.
- `tests/test_context_lifecycle_outbox_foreign_table_authority.py` pins direct/view foreign discovery, the recursive `pg_inherits` ancestor closure, ordinary/partitioned parent reachability, and inherited foreign-source membership for materialized provenance.
- Causal production repair `0c2bf9bb991d3556a2d27de8ae8614b138b06c4b` adds the foreign-ancestor closure without changing tenant data SQL, RLS policy, FDW mappings, or caller ACLs.
- Existing ordinary-view, local materialized-outbox, `SECURITY DEFINER`, role-admin, RLS-policy, DML, and replay-arbiter smokes remain required; this control does not replace them.
- Exact-head GREEN may be claimed only when an unchanged head containing the causal repair passes hosted PostgreSQL/container, Python 3.10/3.12/3.14, coverage/docstring/lint/package, and Release Acceptance gates.

## Consequences and follow-up

The live admission query now computes a recursive foreign-inheritance ancestor set in addition to the existing relation/view/materialized provenance graph. Issue #307 remains the performance owner: buyer acceptance must include catalog size, inheritance depth and fanout, foreign-leaf count, materialized-source depth, connection acquisition, admission, tenant binding, I/O, and cleanup in p50/p95/p99 measurements. Security catalog work may not be omitted or measured only after an unrealistic warm-up to meet the p95 target.

## Primary evidence

PostgreSQL Global Development Group. (n.d.). *Inheritance*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/ddl-inherit.html

PostgreSQL Global Development Group. (n.d.). *Table partitioning*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/ddl-partitioning.html

PostgreSQL Global Development Group. (n.d.). *CREATE FOREIGN TABLE*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createforeigntable.html

PostgreSQL Global Development Group. (n.d.). *postgres_fdw — access data stored in external PostgreSQL servers*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/postgres-fdw.html

PostgreSQL Global Development Group. (n.d.). *CREATE USER MAPPING*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createusermapping.html

PostgreSQL Global Development Group. (n.d.). *pg_class*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/catalog-pg-class.html
