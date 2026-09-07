# ADR 0033: Lifecycle Outbox Foreign-Data Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox runtime is admitted as a narrow PostgreSQL application identity: forced-RLS access to the package-owned outbox with no ambient operator authority. ADRs 0031 and 0032 extend that boundary across role selection, privilege delegation, callable `SECURITY DEFINER` principals, ordinary views, and materialized copies.

Foreign tables introduce a different authority domain. PostgreSQL's `postgres_fdw` uses a foreign server plus a user mapping to determine the remote connection identity, and a local `SELECT` on a foreign table reads the underlying remote relation. A local role can therefore remain `NOBYPASSRLS` while its foreign-table access executes remotely under a different principal whose RLS or ownership semantics are not represented by the local outbox catalogs.

Hosted CI on exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c` reproduced the first gap. The PostgreSQL/container job created a loopback `postgres_fdw` server and mapped the ordinary local runtime role to a distinct remote `BYPASSRLS` role. The local outbox returned one `tenant-a` row, while the foreign relation returned both seeded tenants. Production admission accepted that credential. A second specimen hid the same foreign relation behind an ordinary owner-rights view, proving that direct caller privileges alone are insufficient.

Review of that repair exposed a separate copied-data path. A materialized view may read the foreign relation while it is populated, storing the remote cross-tenant result locally. The runtime can later read that materialized relation even after its own direct foreign-table privilege has been removed and without establishing a new remote connection. Existing materialized provenance protected copies derived from the local lifecycle outbox, but did not reject a reachable materialized relation whose provenance terminated at an opaque foreign table. Executable RED `9479d11d8141cc799d4ae671e1d852efb97442d1` and static RED `2c3a6a58cc6a8613c9ad5630693caa81d69a29be` preserve that distinction.

A third path exists through PostgreSQL inheritance. PostgreSQL 18 documents that inherited queries check access permission on the named parent table, and that the parent's row-security policies govern rows returned from children. It also permits foreign tables in inheritance hierarchies, and declarative partitions may themselves be foreign tables. Consequently, a local runtime role can hold `SELECT` only on an ordinary or partitioned parent while a foreign descendant executes through a remote user mapping that the local RLS catalogs cannot prove. Exact RED `be5e0abe55586b6e23a867e9c05a9845133310bc`, CI `34081839661`, PostgreSQL/container job `101618458532` reproduced this with a parent-only `SELECT`: the local forced-RLS outbox returned one tenant row while a partitioned parent with a foreign default partition returned both remote rows, and production admission accepted it.

The package cannot establish durable remote authorization by parsing local FDW options. The foreign server may point elsewhere; the foreign-data wrapper may not be `postgres_fdw`; user mappings and remote ACL/RLS state are mutable independently of this package. An allowlist of server names, remote role strings, table-option text, partition bounds, or parent names would therefore turn mutable configuration into unverified security evidence. The same limitation applies after copying: current materialized contents and the authority used by the last refresh are not durable proof of tenant isolation.

## Decision

Treat foreign data (`pg_class.relkind = 'f'`) as an opaque authority boundary for the lifecycle-outbox runtime credential, whether the foreign relation is reached directly, through an ordinary view, through an inheritance/partition parent, or as materialized-copy provenance.

The admission query builds a cycle-safe `foreign_inheritance_ancestor(relation_oid)` closure upward from every foreign relation through `pg_inherits`. The existing `reachable_relation(relation_oid, caller_oid)` and materialized provenance closures then enforce the boundary:

1. a foreign table directly selectable by an effective/session-selectable runtime principal is reachable;
2. an ordinary view may reach a foreign table or a foreign-bearing inheritance parent only when the principal PostgreSQL applies at that edge can select it — the original invoker for `security_invoker=true`, otherwise the current view owner;
3. an ordinary or partitioned parent is rejected when the `pg_inherits` ancestor closure proves any descendant is a foreign relation, even if the caller has no direct privilege on that child;
4. a reachable materialized view is rejected when any relation in its cycle-safe stored-definition provenance is the lifecycle outbox or belongs to the foreign inheritance-ancestor closure, even when the caller cannot currently select the source foreign relation or descendant;
5. any of those paths causes fail-closed runtime admission before tenant binding or lifecycle outbox data SQL.

The materialized rule is source-based rather than content-based. The package does not inspect copied rows, infer a tenant from definition text, trust partition constraints as remote authorization, or trust last-refresh authority. Once a reachable materialized copy depends on opaque foreign data, directly or through an inheritance parent, local catalog evidence is insufficient to establish that the copy is tenant-safe.

The guard does not inspect or trust FDW type, foreign-server options, user-mapping options, remote user names, remote table names, remote ownership, remote RLS policy, partition bounds, or child ACLs. PostgreSQL's parent-query privilege semantics are the reason child ACL absence is not accepted as evidence. The package also does not revoke ACLs or alter mappings. Workloads that need foreign-data access must separate that authority into another role/connection rather than combine it with the lifecycle-outbox credential.

This is intentionally conservative. A reachable foreign table, foreign-bearing inheritance parent, or reachable materialized copy sourced from foreign data is rejected even when it is currently unrelated to the lifecycle outbox because the package cannot prove that its remote target, authorization, or copied-data semantics remain unrelated for the lifetime of the credential. The isolation claim is narrower and auditable: the outbox runtime credential has neither selectable foreign-data authority nor parent-mediated/copy-mediated foreign-data authority.

## Alternatives considered

### Inspect only `postgres_fdw` user mappings for `BYPASSRLS`

Rejected. `BYPASSRLS` is a role attribute on a PostgreSQL server, not a portable local user-mapping property. Even for loopback `postgres_fdw`, the mapping's `user` option is a name, not durable proof of the remote role attributes. External servers make local verification impossible without introducing a second trust/availability boundary.

### Allow foreign tables whose options do not name the lifecycle outbox

Rejected. Foreign-table and server options are wrapper-specific and mutable, and the remote relation may be renamed, exposed through a view, inherited through a parent, or changed independently. Textual names are not authorization evidence.

### Reject only foreign tables directly selectable by the runtime caller

Rejected. PostgreSQL ordinary views can execute underlying relation access with the view owner's permissions unless `security_invoker=true`, and inherited queries check privileges on the named parent rather than requiring a separate child grant. Hosted specimens prove both paths.

### Trust missing child `SELECT` on a foreign partition or inheritance child

Rejected. PostgreSQL documents that inherited queries perform permission checks on the parent table only. Declarative partition hierarchies use inheritance internally, and foreign tables are valid partitions. Child ACL absence therefore does not remove parent-mediated remote access.

### Accept a materialized copy after direct foreign-table access is revoked

Rejected. The copied rows remain readable without another remote access. Revoking the source privilege changes future execution authority; it does not retroactively reapply local RLS to already-persisted rows.

### Parse materialized-view SQL or partition bounds and accept an apparent tenant predicate

Rejected. SQL text, partition metadata, and copied rows are mutable state; none proves the remote principal or remote RLS context used during population or inherited execution. Catalog dependency/inheritance structure is the narrower durable structure to inspect, and a foreign source remains opaque.

### Disable or drop foreign tables automatically

Rejected. Runtime package code does not own database authorization or integration policy. The package reports an unsafe admission boundary; operators repair roles, ACLs, views, materialized views, inheritance/partition topology, servers, and mappings.

## Verification

- First hosted reality RED: exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c`, CI run `34077132444`, PostgreSQL/container job `101605370280`.
- Copied-foreign executable RED: `tests/smoke_context_lifecycle_outbox_foreign_table_authority.sh` at `9479d11d8141cc799d4ae671e1d852efb97442d1` creates a materialized copy under the mapped foreign authority, removes caller direct foreign `SELECT`, proves the copy still contains both tenants, and requires package admission to reject it.
- Parent-mediated executable RED: exact head `be5e0abe55586b6e23a867e9c05a9845133310bc`, CI `34081839661`, PostgreSQL/container job `101618458532`; `tests/smoke_context_lifecycle_outbox_partitioned_foreign_authority.sh` grants the runtime `SELECT` only on a partitioned parent, proves no direct child `SELECT`, then proves the parent returns both remote tenants and requires package admission to reject the path.
- Static contract: `tests/test_context_lifecycle_outbox_foreign_table_authority.py` pins direct/view foreign discovery, the `pg_inherits` foreign-ancestor closure, ordinary/partitioned parent reachability, and inherited foreign-source detection in materialized provenance.
- Causal inheritance repair `0c2bf9bb991d3556a2d27de8ae8614b138b06c4b` extends admission with the cycle-safe upward foreign-ancestor closure while preserving the existing view-effective-principal and materialized-provenance semantics.
- Existing role, RLS-policy, `SECURITY DEFINER`, ordinary-view, local materialized-view, replay, migration, and package gates remain mandatory.
- This ADR remains Proposed until one unchanged exact PR head passes hosted CI and Release Acceptance and is integrated through the protected-branch workflow.

## Operational effect

Issue #307 owns the buyer performance envelope. The foreign-relation catalog scan, recursive `pg_inherits` ancestor closure, view graph, and materialized-source membership checks are part of the security admission cost and must remain inside connection-to-cleanup p50/p95/p99 measurements. Performance work may optimize catalog access but may not exclude the authority check, prune realistic inheritance depth/fanout, assume a warm cache solely to meet the target, or weaken fail-closed semantics.

## References

PostgreSQL Global Development Group. (n.d.). *Inheritance*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/ddl-inherit.html

PostgreSQL Global Development Group. (n.d.). *Table partitioning*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/ddl-partitioning.html

PostgreSQL Global Development Group. (n.d.). *CREATE FOREIGN TABLE*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createforeigntable.html

PostgreSQL Global Development Group. (n.d.). *postgres_fdw — access data stored in external PostgreSQL servers*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/postgres-fdw.html

PostgreSQL Global Development Group. (n.d.). *CREATE USER MAPPING*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createusermapping.html

PostgreSQL Global Development Group. (n.d.). *pg_class*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/catalog-pg-class.html
