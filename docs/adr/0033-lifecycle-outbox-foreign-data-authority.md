# ADR 0033: Lifecycle Outbox Foreign-Data Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox runtime is admitted as a narrow PostgreSQL application identity: forced-RLS access to the package-owned outbox with no ambient operator authority. ADRs 0031 and 0032 extend that boundary across role selection, privilege delegation, callable `SECURITY DEFINER` principals, ordinary views, and materialized copies.

Foreign tables introduce a different authority domain. PostgreSQL's `postgres_fdw` uses a foreign server plus a user mapping to determine the remote connection identity, and a local `SELECT` on a foreign table reads the underlying remote relation. A local role can therefore remain `NOBYPASSRLS` while its foreign-table access executes remotely under a different principal whose RLS or ownership semantics are not represented by the local outbox catalogs.

Hosted CI on exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c` reproduced the first gap. The PostgreSQL/container job created a loopback `postgres_fdw` server and mapped the ordinary local runtime role to a distinct remote `BYPASSRLS` role. The local outbox returned one `tenant-a` row, while the foreign relation returned both seeded tenants. Production admission accepted that credential. A second specimen hid the same foreign relation behind an ordinary owner-rights view, proving that direct caller privileges alone are insufficient.

Review of that repair exposed a separate copied-data path. A materialized view may read the foreign relation while it is populated, storing the remote cross-tenant result locally. The runtime can later read that materialized relation even after its own direct foreign-table privilege has been removed and without establishing a new remote connection. Existing materialized provenance protected copies derived from the local lifecycle outbox, but did not reject a reachable materialized relation whose provenance terminated at an opaque foreign table. Executable RED `9479d11d8141cc799d4ae671e1d852efb97442d1` and static RED `2c3a6a58cc6a8613c9ad5630693caa81d69a29be` preserve that distinction.

A third path exists through PostgreSQL inheritance. PostgreSQL 18 documents that inherited queries check access permission on the named parent table, and that the parent's row-security policies govern rows returned from children. It also permits foreign tables in inheritance hierarchies, and declarative partitions may themselves be foreign tables. Consequently, a local runtime role can hold `SELECT` only on an ordinary or partitioned parent while a foreign descendant executes through a remote user mapping that the local RLS catalogs cannot prove. Exact RED `be5e0abe55586b6e23a867e9c05a9845133310bc`, CI `34081839661`, PostgreSQL/container job `101618458532` reproduced this with a parent-only `SELECT`: the local forced-RLS outbox returned one tenant row while a partitioned parent with a foreign default partition returned both remote rows, and production admission accepted it.

A fourth execution route crosses the callable `SECURITY DEFINER` boundary. PostgreSQL executes a `SECURITY DEFINER` function with the privileges of its owner, while `postgres_fdw` resolves remote access through the local user mapping that applies to the executing database principal. A runtime caller can therefore have no direct `SELECT` on a foreign relation yet still execute a user-schema definer owned by an otherwise ordinary `NOSUPERUSER NOBYPASSRLS` role that can select the foreign relation through its own mapping. A canonical routine `search_path = pg_catalog, pg_temp` prevents name-resolution substitution but does not remove the owner's authorized foreign-data capability. Test-first commits `8b6cbc130faee66f22d975f2fcc19330d97d4eab`, `076a7d788e385bcefc9f3de2882293b44bd8eab1`, and `01a93f666cd25c9cb25ed152d17b344ae49b3025` preserve an executable loopback specimen and a static query-shape contract before the production repair.

A fifth route combines callable-definer authority with mutable role administration. PostgreSQL role membership separates current inheritance/SET capability from `ADMIN OPTION`: a role administrator can grant the administered role to another principal even when the administrator's own membership is `INHERIT FALSE, SET FALSE`. The new membership may itself be granted with `SET TRUE`, and `SET ROLE` may then traverse an indirect membership chain when every edge permits SET. A callable safe-search-path `SECURITY DEFINER` can therefore execute under an ordinary owner that has no direct foreign-table `SELECT`, but owns `ADMIN OPTION` over a bridge role whose all-SET descendants include a foreign-reader role. Exact hosted RED `0b4767fb0fc96cc6e33edd0acfeffdb96e72dd6c`, CI `34086576574`, Python 3.14 job `101631664289`, and PostgreSQL/container job `101631664178` reproduced this: the runtime caller's bridge membership was revoked before admission, the definer re-granted the bridge with SET authority, and the caller then reached the foreign reader and obtained both remote tenants. Missing current caller SET membership and missing direct caller/definer foreign ACLs were therefore not durable proof of safety.

The package cannot establish durable remote authorization by parsing local FDW options. The foreign server may point elsewhere; the foreign-data wrapper may not be `postgres_fdw`; user mappings and remote ACL/RLS state are mutable independently of this package. An allowlist of server names, remote role strings, table-option text, partition bounds, parent names, callable routine body text, or current membership shape would therefore turn mutable configuration into unverified security evidence. The same limitation applies after copying: current materialized contents and the authority used by the last refresh are not durable proof of tenant isolation.

## Decision

Treat foreign data (`pg_class.relkind = 'f'`) as an opaque authority boundary for the lifecycle-outbox runtime credential, whether the foreign relation is reached directly, through an ordinary view, through an inheritance/partition parent, through a callable `SECURITY DEFINER` owner's executable relation authority, through roles that callable owner can mint/select via membership administration, or as materialized-copy provenance.

The admission query builds a cycle-safe `foreign_inheritance_ancestor(relation_oid)` closure upward from every foreign relation through `pg_inherits`. The existing `reachable_relation(relation_oid, caller_oid)` and materialized provenance closures then enforce the boundary:

1. a foreign table directly selectable by an effective/session-selectable runtime principal is reachable;
2. an ordinary view may reach a foreign table or a foreign-bearing inheritance parent only when the principal PostgreSQL applies at that edge can select it — the original invoker for `security_invoker=true`, otherwise the current view owner;
3. an ordinary or partitioned parent is rejected when the `pg_inherits` ancestor closure proves any descendant is a foreign relation, even if the caller has no direct privilege on that child;
4. a reachable materialized view is rejected when any relation in its cycle-safe stored-definition provenance is the lifecycle outbox or belongs to the foreign inheritance-ancestor closure, even when the caller cannot currently select the source foreign relation or descendant;
5. every callable user-schema `SECURITY DEFINER` owner in the existing cycle-safe routine-owner closure is evaluated through the same reachable relation/materialized/foreign-data probe, so owner-only foreign authority is rejected even when the runtime caller lacks direct relation `SELECT`;
6. for every role that a callable definer owner can administer through `MEMBER WITH ADMIN OPTION`, and every role that administered principal can reach through an all-SET path, admission applies the same reachable relation/materialized/inheritance/foreign-data probe. The boundary therefore rejects latent post-return authority that a callable definer can mint with `GRANT ... WITH SET TRUE` even when the current caller cannot yet `SET ROLE` to the bridge or foreign reader; and
7. any of those paths causes fail-closed runtime admission before tenant binding or lifecycle outbox data SQL.

The definer rule is authority-based, not function-body-based. Admission does not attempt to prove that one current routine body does or does not reference a foreign relation or issue a membership grant. SQL, PL/pgSQL, dynamic SQL, nested routines, future routine replacement, view indirection, inheritance, mutable mappings, and mutable membership make body inspection an incomplete continuing authorization proof. If a callable definer owner can reach opaque foreign data directly, or can administer/select a principal that can, that owner is outside the lifecycle-outbox credential envelope; the workload must separate the capability into another role/connection.

The materialized rule is source-based rather than content-based. The package does not inspect copied rows, infer a tenant from definition text, trust partition constraints as remote authorization, or trust last-refresh authority. Once a reachable materialized copy depends on opaque foreign data, directly or through an inheritance parent, local catalog evidence is insufficient to establish that the copy is tenant-safe.

The guard does not inspect or trust FDW type, foreign-server options, user-mapping options, remote user names, remote table names, remote ownership, remote RLS policy, partition bounds, child ACLs, current caller role selection, or current function body text. PostgreSQL's parent-query privilege semantics are the reason child ACL absence is not accepted as evidence; PostgreSQL's definer execution semantics are the reason caller ACL absence is not accepted as evidence once execution crosses to the owner; PostgreSQL's role-administration semantics are the reason current caller SET membership is not accepted as a stable upper bound when a callable owner can grant a selectable bridge after admission. The package also does not revoke ACLs or alter mappings/memberships. Workloads that need foreign-data or role-administration access must separate that authority into another role/connection rather than combine it with the lifecycle-outbox credential.

This is intentionally conservative. A reachable foreign table, foreign-bearing inheritance parent, callable definer owner with such relation or delegation authority, administered/all-SET-reachable role with such authority, or reachable materialized copy sourced from foreign data is rejected even when it is currently unrelated to the lifecycle outbox because the package cannot prove that its remote target, authorization, routine behavior, delegated membership, or copied-data semantics remain unrelated for the lifetime of the credential. The isolation claim is narrower and auditable: the outbox runtime credential has neither selectable foreign-data authority nor parent-mediated, definer-mediated, delegation-mediated, or copy-mediated foreign-data authority.

## Alternatives considered

### Inspect only `postgres_fdw` user mappings for `BYPASSRLS`

Rejected. `BYPASSRLS` is a role attribute on a PostgreSQL server, not a portable local user-mapping property. Even for loopback `postgres_fdw`, the mapping's `user` option is a name, not durable proof of the remote role attributes. External servers make local verification impossible without introducing a second trust/availability boundary.

### Allow foreign tables whose options do not name the lifecycle outbox

Rejected. Foreign-table and server options are wrapper-specific and mutable, and the remote relation may be renamed, exposed through a view, inherited through a parent, or changed independently. Textual names are not authorization evidence.

### Reject only foreign tables directly selectable by the runtime caller

Rejected. PostgreSQL ordinary views can execute underlying relation access with the view owner's permissions unless `security_invoker=true`, inherited queries check privileges on the named parent rather than requiring a separate child grant, and `SECURITY DEFINER` routines execute with their owner's privileges. The caller's direct relation ACL therefore does not bound all executable remote authority.

### Inspect only the current callable function body or dependency graph

Rejected. The security boundary is the executable owner principal, not one textual routine snapshot. Dynamic SQL, procedural languages, nested routines, view/materialized/inheritance indirection, owner privilege changes, membership grants, and routine replacement can alter which foreign relation or foreign-capable role is reached without making body-text parsing a durable authorization proof. The conservative principal-authority probe is explicit and testable.

### Trust `INHERIT FALSE, SET FALSE` on a definer owner's administered membership

Rejected. Those options constrain how the owner currently inherits or assumes the administered role; they do not remove `ADMIN OPTION`. An administrator can grant that role to another principal and may grant the new edge with SET authority. A callable definer can perform that grant while executing as its owner, so the runtime caller's pre-admission membership graph is not an immutable ceiling.

### Check only the current runtime caller's `SET ROLE` closure

Rejected. The hosted RED removes the caller's bridge membership before admission and still succeeds after the callable definer re-grants the bridge with SET authority. Admission must therefore include the callable owner's membership-administration capability and the all-SET authority reachable from the administered role, rather than only the caller's current selectable closure.

### Trust missing child `SELECT` on a foreign partition or inheritance child

Rejected. PostgreSQL documents that inherited queries perform permission checks on the parent table only. Declarative partition hierarchies use inheritance internally, and foreign tables are valid partitions. Child ACL absence therefore does not remove parent-mediated remote access.

### Accept a materialized copy after direct foreign-table access is revoked

Rejected. The copied rows remain readable without another remote access. Revoking the source privilege changes future execution authority; it does not retroactively reapply local RLS to already-persisted rows.

### Parse materialized-view SQL or partition bounds and accept an apparent tenant predicate

Rejected. SQL text, partition metadata, and copied rows are mutable state; none proves the remote principal or remote RLS context used during population or inherited execution. Catalog dependency/inheritance structure is the narrower durable structure to inspect, and a foreign source remains opaque.

### Disable or drop foreign tables or memberships automatically

Rejected. Runtime package code does not own database authorization or integration policy. The package reports an unsafe admission boundary; operators repair roles, memberships, ACLs, routines, views, materialized views, inheritance/partition topology, servers, and mappings.

## Verification

- First hosted reality RED: exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c`, CI run `34077132444`, PostgreSQL/container job `101605370280`.
- Copied-foreign executable RED: `tests/smoke_context_lifecycle_outbox_foreign_table_authority.sh` at `9479d11d8141cc799d4ae671e1d852efb97442d1` creates a materialized copy under the mapped foreign authority, removes caller direct foreign `SELECT`, proves the copy still contains both tenants, and requires package admission to reject it.
- Parent-mediated executable RED: exact head `be5e0abe55586b6e23a867e9c05a9845133310bc`, CI `34081839661`, PostgreSQL/container job `101618458532`; `tests/smoke_context_lifecycle_outbox_partitioned_foreign_authority.sh` grants the runtime `SELECT` only on a partitioned parent, proves child `SELECT` is absent, proves the parent still returns both remote tenants, and requires package admission to reject the path.
- Definer-mediated test-first RED: `tests/smoke_context_lifecycle_outbox_security_definer_foreign_authority.sh` at `8b6cbc130faee66f22d975f2fcc19330d97d4eab` creates an ordinary local definer owner mapped to a remote `BYPASSRLS` role, proves the runtime caller has no direct foreign-table `SELECT`, and proves the safe-search-path `SECURITY DEFINER` can nevertheless return both tenants. Static RED `076a7d788e385bcefc9f3de2882293b44bd8eab1` requires the admission query to evaluate foreign relation authority under `definer_role.oid`; CI wiring head `01a93f666cd25c9cb25ed152d17b344ae49b3025` makes the PostgreSQL specimen part of the required container lane.
- Causal direct-definer repair `7367d4864488b21abfd74b389dba38f208e6c6ca` reuses the existing reachable relation/materialized/foreign authority probe for each callable definer owner without changing tenant data SQL, RLS policy, FDW mappings, caller ACLs, or routine bodies.
- Delegated-definer executable RED: exact `0b4767fb0fc96cc6e33edd0acfeffdb96e72dd6c`, CI `34086576574`, Python 3.14 job `101631664289`, PostgreSQL/container job `101631664178`. The unit contract failed `1 failed, 1624 passed, 7 deselected` because the admission query did not evaluate reachable foreign authority under `definer_admin_role.oid`; the PostgreSQL specimen proved the callable owner could re-grant a bridge with SET authority and expose the opaque foreign-reader mapping.
- Causal delegated-definer repair `7700cece8a860641457b3c5b2ef5bcceff2d0c56` applies the same reachable relation/materialized/inheritance/foreign-data probe to `definer_admin_role.oid` and `definer_admin_set_role.oid`. It is one production-file commit (`+11/-1`) and changes no tenant data SQL, RLS policy, FDW mapping, routine body, workflow gate, or protected ref.
- Exact repair head `7700cece8a860641457b3c5b2ef5bcceff2d0c56`: Release Acceptance `34087417982` is terminal success; CI `34087418005` remains in progress at the time of this ADR update. No exact-current GREEN is claimed until that CI reaches terminal success unchanged.
- Static contract: `tests/test_context_lifecycle_outbox_foreign_table_authority.py` pins direct/view foreign discovery, the `pg_inherits` foreign-ancestor closure, ordinary/partitioned parent reachability, inherited foreign-source detection in materialized provenance, direct definer-owner foreign relation evaluation, and delegated definer-admin/all-SET foreign relation evaluation.
- Existing role, RLS-policy, `SECURITY DEFINER`, ordinary-view, local materialized-view, replay, migration, and package gates remain mandatory.
- This ADR remains Proposed until one unchanged exact PR head containing the causal repair passes hosted CI and Release Acceptance and is integrated through the protected-branch workflow.

## Operational effect

Issue #307 owns the buyer performance envelope. The foreign-relation catalog scan, recursive `pg_inherits` ancestor closure, view graph, materialized-source membership checks, and the same authority scan under callable definer owners, administered-role fanout, and all-SET reachable roles are part of the security admission cost and must remain inside connection-to-cleanup p50/p95/p99 measurements. Performance work must vary definer cardinality/depth, ADMIN-option fanout, all-SET depth/fanout, and the reachable relation/view/materialized/foreign/inheritance graph under those principals. It may optimize catalog access but may not exclude the authority check, prune realistic delegation/inheritance cardinality, assume a warm cache solely to meet the target, or weaken fail-closed semantics.

## References

PostgreSQL Global Development Group. (n.d.). *Inheritance*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/ddl-inherit.html

PostgreSQL Global Development Group. (n.d.). *Table partitioning*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/ddl-partitioning.html

PostgreSQL Global Development Group. (n.d.). *CREATE FOREIGN TABLE*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createforeigntable.html

PostgreSQL Global Development Group. (n.d.). *postgres_fdw — access data stored in external PostgreSQL servers*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/postgres-fdw.html

PostgreSQL Global Development Group. (n.d.). *CREATE USER MAPPING*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createusermapping.html

PostgreSQL Global Development Group. (n.d.). *CREATE FUNCTION*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createfunction.html

PostgreSQL Global Development Group. (n.d.). *Function security*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/perm-functions.html

PostgreSQL Global Development Group. (n.d.). *Role membership*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/role-membership.html

PostgreSQL Global Development Group. (n.d.). *SET ROLE*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-set-role.html

PostgreSQL Global Development Group. (n.d.). *Role attributes*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/role-attributes.html

PostgreSQL Global Development Group. (n.d.). *pg_class*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/catalog-pg-class.html
