# Architecture

## Deployment boundary

`pg-llm-batch` remains independently deployable and embeddable. PostgreSQL owns
configuration, encrypted secrets, token counting, JSONL payloads, and durable
provider lifecycle state. Provider HTTP behavior remains behind
`BatchAPIClient`, while host services may inject credential, observation-order,
and lifecycle-persistence seams without changing provider semantics.

## Durable lifecycle tenancy

`DurableBatchAPIClient` is the backward-compatible standalone facade.
`TenantDurableBatchAPIClient` requires a tenant scope selected by a trusted host
after authentication and authorization. The durable business identity is:

```text
(tenant_scope, endpoint_alias, remote_batch_id)
```

Package reads and writes bind the validated scope with parameterized,
transaction-local `set_config('pg_llm_batch.tenant_scope', ..., true)`.
PostgreSQL row-level security is enabled and forced, so missing context is
default-deny for ordinary application roles. PostgreSQL superusers and roles
with `BYPASSRLS` remain administrative escape hatches and must not be used as
application identities.

Lifecycle-outbox RLS policy authority is catalog-verified, not name-inferred.
Canonical v2 uses `OPERATOR(pg_catalog.=)` and `pg_catalog.current_setting` for
both `USING` and `WITH CHECK`. Migration 0008 accepts an existing v2 without DDL
only when `pg_policy` proves all-command permissive `PUBLIC` scope and both
stored expression trees decompile to the canonical tenant predicate. A
same-name drifted v2 is replaced, an unknown policy name fails the migration
instead of being silently retained or deleted, and the canonical catalog state
is verified again before v1/legacy policies are retired. Policy names remain
version markers rather than security evidence.

Lifecycle-outbox runtime relation authority is explicit without rewriting
caller transaction state. Tenant binding calls `pg_catalog.set_config` directly,
and runtime reads/writes address
`public.llm_context_lifecycle_outbox`. The earlier candidate that used
`SET LOCAL search_path` in this caller-owned seam was superseded because its
name-resolution change would persist for unrelated domain SQL until transaction
end.

Migration 0008 and its destructive rollback are installer-owned atomic
statements and bind `pg_catalog, public, pg_temp` with fully qualified
`pg_catalog.set_config` inside their `DO` blocks before object lookup or DDL.
Explicit `pg_temp` placement prevents the temporary schema from receiving
implicit relation precedence over the reviewed `public` application schema in
those statements. This does not make `public` safe if operators grant untrusted
principals `CREATE` there; schema ACLs remain part of the deployment trust
boundary.

The custom setting is part of a **trusted application boundary**. It is not a
credential and is not a substitute for authentication, authorization,
SQL-injection prevention, or restricted direct database access. A role capable
of arbitrary SQL can call `set_config` with an arbitrary tenant scope. CWL hosts
must therefore expose tenant lifecycle operations through parameterized package
APIs or a separately reviewed identity-to-role interface, not a generic SQL
surface.

Provider metadata, endpoint aliases, provider resource identifiers, payloads,
model output, and transport headers never select tenant authorization context.

## Migration and rollback

Legacy lifecycle rows are backfilled to `standalone` without deletion or
identity merging. The prior endpoint/provider unique key is replaced by a
tenant-qualified key. The owner-enforcement transition, backfill, constraint
migration, and forced-RLS restoration execute in one PostgreSQL anonymous block
so psql autocommit cannot commit an intermediate owner-bypass state.

Enabling RLS changes the behavior of direct SQL integrations: an ordinary role
that does not bind an authorized transaction-local scope sees no lifecycle
rows. Those integrations must move to `get_remote_batch_state`,
`get_tenant_remote_batch_state`, or a reviewed tenant-binding database interface
before deployment. Caller-owned outbox methods require a real transaction for
the transaction-local tenant setting, but preserve the caller's existing
`search_path`.

Rollback to the former two-column key is unsafe until an operator proves that no
`(endpoint_alias, remote_batch_id)` pair exists in more than one tenant scope.
The rollback binds reviewed name resolution before `to_regclass`, emptiness
inspection, and `DROP TABLE`. The packaged schema and Docker initialization
schema are maintained as exact mirrors and must be reapplied successfully more
than once.

## Logical restore execution

`restore_postgres_logical_backup()` is a bounded direct-SQL restore seam. The
caller must pass exact-boolean `source_superusers_trusted=True` and select an
isolated libpq service; the service name is not an authorization or
proof-of-isolation boundary. Only `PGPASSWORD`, `PGPASSFILE`, and
`PGSERVICEFILE` may be inherited. The child runs
`pg_restore --single-transaction --exit-on-error --dbname=service=...`.

Custom-format `pg_restore` seeks to the table of contents and data blocks, so a
successful restore is not required to leave the descriptor at end-of-file.
Post-restore metadata mismatch is fail-closed and must be treated as unsafe
because the SQL transaction may already have committed. This seam does not
complete isolated schema/RLS/PITR acceptance.

## Modular interoperability

CWL hosts such as `contextual-orchestrator` and `naruon` supply tenant context
only after their own authentication and authorization boundary. The package
does not require either host and retains standalone operation. When embedded,
tenant scope is a local control-plane identity and not model- or
provider-returned data.

## Verification boundary

Deterministic gates cover strict tenant validation, standalone compatibility,
tenant-qualified SQL parameters, current-state reconciliation, migration
idempotency, malformed database rows, default-deny policy text, explicit
`pg_catalog` policy predicate authority, `pg_policy` command/role/expression
identity, unknown-policy fail-closed behavior, post-repair canonical policy
verification, runtime schema qualification without caller `search_path`
mutation, installer/rollback search-path authority, schema mirroring, operator
documentation, and 100% production statement and branch coverage. Live
PostgreSQL isolation tests use a `NOSUPERUSER NOBYPASSRLS` role and prove that
identical provider identifiers in different tenants remain independently
addressable and mutually invisible when access occurs through the trusted
package boundary. Exact-head runtime evidence must also exercise a non-default
caller `search_path`, verify the canonical outbox relation is still selected,
verify the caller path is unchanged afterward, and execute migration 0008 so its
catalog postcondition is checked by PostgreSQL itself. These tests do not claim
isolation after arbitrary SQL or untrusted schema-creation authority is granted.
