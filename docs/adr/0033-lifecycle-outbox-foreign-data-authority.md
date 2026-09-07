# ADR 0033: Lifecycle Outbox Foreign-Data Authority

- Status: Proposed
- Date: 2026-09-07

## Context

The lifecycle-outbox runtime is admitted as a narrow PostgreSQL application identity: forced-RLS access to the package-owned outbox with no ambient operator authority. ADRs 0031 and 0032 extend that boundary across role selection, privilege delegation, callable `SECURITY DEFINER` principals, ordinary views, and materialized copies.

Foreign tables introduce a different authority domain. PostgreSQL's `postgres_fdw` uses a foreign server plus a user mapping to determine the remote connection identity, and a local `SELECT` on a foreign table reads the underlying remote relation. A local role can therefore remain `NOBYPASSRLS` while its foreign-table access executes remotely under a different principal whose RLS or ownership semantics are not represented by the local outbox catalogs.

Hosted CI on exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c` reproduced the first gap. The PostgreSQL/container job created a loopback `postgres_fdw` server and mapped the ordinary local runtime role to a distinct remote `BYPASSRLS` role. The local outbox returned one `tenant-a` row, while the foreign relation returned both seeded tenants. Production admission accepted that credential. A second specimen hid the same foreign relation behind an ordinary owner-rights view, proving that direct caller privileges alone are insufficient.

Review of that repair exposed a separate copied-data path. A materialized view may read the foreign relation while it is populated, storing the remote cross-tenant result locally. The runtime can later read that materialized relation even after its own direct foreign-table privilege has been removed and without establishing a new remote connection. Existing materialized provenance protected copies derived from the local lifecycle outbox, but did not reject a reachable materialized relation whose provenance terminated at an opaque foreign table. Executable RED `9479d11d8141cc799d4ae671e1d852efb97442d1` and static RED `2c3a6a58cc6a8613c9ad5630693caa81d69a29be` preserve that distinction.

The package cannot establish durable remote authorization by parsing local FDW options. The foreign server may point elsewhere; the foreign-data wrapper may not be `postgres_fdw`; user mappings and remote ACL/RLS state are mutable independently of this package. An allowlist of server names, remote role strings, or table-option text would therefore turn mutable configuration into unverified security evidence. The same limitation applies after copying: current materialized contents and the authority used by the last refresh are not durable proof of tenant isolation.

## Decision

Treat a user-schema foreign table (`pg_class.relkind = 'f'`) as an opaque authority boundary for the lifecycle-outbox runtime credential, both for live execution and for reachable materialized-copy provenance.

The existing cycle-safe `reachable_relation(relation_oid, caller_oid)` graph and materialized provenance closure enforce the boundary:

1. a foreign table directly selectable by an effective/session-selectable runtime principal is reachable;
2. an ordinary view may reach a foreign table only when the principal PostgreSQL applies at that edge can select it — the original invoker for `security_invoker=true`, otherwise the current view owner;
3. a reachable materialized view is rejected when any relation in its cycle-safe stored-definition provenance is a foreign table, even when the caller cannot currently select the source foreign relation;
4. a reachable foreign table or foreign-sourced materialized copy causes fail-closed runtime admission before tenant binding or lifecycle outbox data SQL.

The materialized rule is source-based rather than content-based. The package does not inspect copied rows, infer a tenant from definition text, or trust last-refresh authority. Once a reachable materialized copy depends on opaque foreign data, local catalog evidence is insufficient to establish that the copy is tenant-safe.

The guard does not inspect or trust FDW type, foreign-server options, user-mapping options, remote user names, remote table names, remote ownership, or remote RLS policy. It also does not revoke ACLs or alter mappings. Workloads that need foreign-data access must separate that authority into another role/connection rather than combine it with the lifecycle-outbox credential.

This is intentionally conservative. A reachable foreign table, or a reachable materialized copy sourced from foreign data, is rejected even when it is currently unrelated to the lifecycle outbox because the package cannot prove that its remote target, authorization, or copied-data semantics remain unrelated for the lifetime of the credential. The isolation claim is narrower and auditable: the outbox runtime credential has neither selectable foreign-data authority nor selectable copied foreign-data authority.

## Alternatives considered

### Inspect only `postgres_fdw` user mappings for `BYPASSRLS`

Rejected. `BYPASSRLS` is a role attribute on a PostgreSQL server, not a portable local user-mapping property. Even for loopback `postgres_fdw`, the mapping's `user` option is a name, not durable proof of the remote role attributes. External servers make local verification impossible without introducing a second trust/availability boundary.

### Allow foreign tables whose options do not name the lifecycle outbox

Rejected. Foreign-table and server options are wrapper-specific and mutable, and the remote relation may be renamed, exposed through a view, or changed independently. Textual names are not authorization evidence.

### Reject only foreign tables directly selectable by the runtime caller

Rejected. PostgreSQL ordinary views can execute underlying relation access with the view owner's permissions unless `security_invoker=true`. The hosted specimen proves that an outer view can expose a foreign relation the caller cannot select directly.

### Accept a materialized copy after direct foreign-table access is revoked

Rejected. The copied rows remain readable without another remote access. Revoking the source privilege changes future execution authority; it does not retroactively reapply local RLS to already-persisted rows.

### Parse materialized-view SQL and accept an apparent tenant predicate

Rejected. SQL text and copied rows are mutable state, and local definition text does not prove the remote principal or remote RLS context used during population. The existing catalog dependency provenance is the narrower durable structure to inspect, and a foreign source remains opaque.

### Disable or drop foreign tables automatically

Rejected. Runtime package code does not own database authorization or integration policy. The package reports an unsafe admission boundary; operators repair roles, ACLs, views, materialized views, servers, and mappings.

## Verification

- First hosted reality RED: exact head `6ccc5da4840a9501ca11d9d38150c7a04ec3408c`, CI run `34077132444`, PostgreSQL/container job `101605370280`.
- Copied-foreign executable RED: `tests/smoke_context_lifecycle_outbox_foreign_table_authority.sh` at `9479d11d8141cc799d4ae671e1d852efb97442d1` creates a materialized copy under the mapped foreign authority, removes caller direct foreign `SELECT`, proves the copy still contains both tenants, and requires package admission to reject it.
- Static contract: `tests/test_context_lifecycle_outbox_foreign_table_authority.py` requires direct/ordinary-view discovery of `relkind = 'f'` and foreign-source detection in materialized provenance; copied-source RED is `2c3a6a58cc6a8613c9ad5630693caa81d69a29be`.
- Causal copied-data repair `417979a94c271cde7dc3344bb7f0301fdc497be3` joins materialized provenance sources to `pg_class` and rejects a reachable materialized copy when any retained source node is `relkind = 'f'`, while preserving the existing local-outbox provenance rejection.
- Existing role, RLS-policy, `SECURITY DEFINER`, ordinary-view, local materialized-view, replay, migration, and package gates remain mandatory.
- This ADR remains Proposed until one unchanged exact PR head passes hosted CI and Release Acceptance and is integrated through the protected-branch workflow.

## Operational effect

Issue #307 owns the buyer performance envelope. The foreign-relation catalog scan and materialized-source relation-kind check are part of the security admission cost and must remain inside connection-to-cleanup p50/p95/p99 measurements. Performance work may optimize catalog access but may not exclude the authority check, assume a warm cache solely to meet the target, or weaken fail-closed semantics.

## References

PostgreSQL Global Development Group. (n.d.). *postgres_fdw — access data stored in external PostgreSQL servers*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/postgres-fdw.html

PostgreSQL Global Development Group. (n.d.). *CREATE USER MAPPING*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/sql-createusermapping.html

PostgreSQL Global Development Group. (n.d.). *pg_class*. PostgreSQL 18 documentation. Retrieved September 7, 2026, from https://www.postgresql.org/docs/18/catalog-pg-class.html
