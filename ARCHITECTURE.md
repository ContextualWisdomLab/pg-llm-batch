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

Lifecycle-outbox payload and timestamp CHECK authority is executable catalog
identity, not a constraint name or comment alone. Migration 0008 requires each
canonical CHECK to be validated and inheritable, to carry the expected review
stamp, and to have a `pg_get_expr` result equal to the reviewed definition as
parsed by the same running PostgreSQL server. The migration derives that
comparison value from session-local temporary probe CHECKs, drops the probe,
repairs a drifted package-owned canonical constraint once, and verifies the
stored predicate again. Already-current durable constraints avoid replacement
DDL. The comment remains traceability evidence but cannot by itself make a
same-name different predicate canonical.

Lifecycle-outbox replay idempotency has a separate catalog invariant. Runtime
uses `ON CONFLICT (tenant_scope, evidence_id) DO NOTHING`; migration 0008
therefore converges `uq_llm_context_lifecycle_outbox_tenant_evidence` after
`CREATE TABLE IF NOT EXISTS` and accepts it only as a validated, nondeferrable
UNIQUE constraint over exactly those two columns. A pre-existing table with a
missing, deferrable, wrong-kind, or wrong-column same-name constraint is repaired
once. Existing duplicate durable identities fail migration rather than being
silently merged or discarded. A current canonical replay arbiter is left
untouched on reapplication.

Lifecycle-outbox runtime relation authority is explicit without rewriting
caller transaction state. Tenant binding calls `pg_catalog.set_config` directly,
and runtime reads/writes address
`public.llm_context_lifecycle_outbox`. The earlier candidate that used
`SET LOCAL search_path` in this caller-owned seam was superseded because its
name-resolution change would persist for unrelated domain SQL until transaction
end.

The durable outbox relation itself is also part of the admitted persistence
contract. Migration 0008 accepts only an ordinary (`pg_class.relkind = 'r'`),
logged (`relpersistence = 'p'`) table in `public`. A structurally identical
`UNLOGGED` replacement fails closed before constraint, RLS, or index convergence;
PostgreSQL does not WAL-log unlogged-table data, truncates it after a crash or
unclean shutdown, and does not replicate its contents to standbys. The migration
does not silently issue `SET LOGGED`, because that rewrite and its operational
impact require an operator-controlled reconciliation window.

Exact durable row-shape admission is physical/catalog-aware rather than limited
to SQL-visible columns. Migration 0008 requires exactly the 14 package-owned live
positive-numbered user attributes and also rejects any positive-numbered
`pg_attribute.attisdropped` entry. PostgreSQL retains a dropped column physically
while hiding it from SQL parsing, so `DROP COLUMN` is not treated as proof that a
previously undeclared persistence surface never existed. The migration does not
auto-rewrite the table or reclaim that state; retention, legal-disposal, WAL,
locking, and availability consequences require operator-controlled
reconciliation or rebuild.

Executable table programs are part of the same structural authority. Migration
0008 rejects any non-internal `pg_trigger` attached to the lifecycle outbox and
any `pg_rewrite` rule whose event relation is the outbox before later CHECK, RLS,
UNIQUE, or index convergence. PostgreSQL-internal triggers remain admissible;
unknown user triggers and rules are not silently deleted because the package
cannot prove their ownership, external dependencies, or side effects. ADR 0024
records this boundary and the PostgreSQL catalog evidence behind it.

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

The Context Fabric lifecycle outbox separately converges its runtime replay key
on every migration application. A fresh table receives the canonical UNIQUE
constraint during creation and then satisfies the catalog guard without further
DDL. A pre-existing table must acquire the same validated NOT DEFERRABLE
`(tenant_scope, evidence_id)` constraint before migration succeeds; duplicates
are an explicit operator-reconciliation failure.

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
verification, canonical payload/timestamp CHECK type/validation/inheritance,
same-runtime parsed-expression identity, review-stamp traceability, post-repair
CHECK verification, canonical replay UNIQUE kind/validation/deferrability/column
identity, ordinary logged-public relation identity, exact live-column cardinality,
dropped-column tombstone rejection, non-internal trigger and rewrite-rule
rejection, runtime schema qualification without caller `search_path` mutation,
installer/rollback search-path authority, schema mirroring, operator
documentation, and 100% production statement and branch coverage. Live
PostgreSQL isolation tests use a `NOSUPERUSER NOBYPASSRLS` role and prove that
identical provider identifiers in different tenants remain independently
addressable and mutually invisible when access occurs through the trusted
package boundary. Exact-head runtime evidence must also exercise a non-default
caller `search_path`, verify the canonical outbox relation is still selected,
verify the caller path is unchanged afterward, and execute migration 0008
against stale replay-key, spoofed canonical-CHECK, UNLOGGED-relation,
undeclared-live-column, dropped-column-tombstone, inheritance-edge,
user-trigger, and rewrite-rule variants so PostgreSQL evaluates canonical
policy, CHECK-predicate, UPSERT-arbiter, executable-table-program, and
durability/schema catalog conditions. These tests do not claim isolation after
arbitrary SQL or untrusted schema-creation authority is granted.
