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
before deployment.

Rollback to the former two-column key is unsafe until an operator proves that no
`(endpoint_alias, remote_batch_id)` pair exists in more than one tenant scope.
The packaged schema and Docker initialization schema are maintained as exact
mirrors and must be reapplied successfully more than once.

## Legacy provider-extension retirement

Fresh installations do not create `http`, `pg_cron`, database-side provider
networking, or an independent provider polling schedule. Existing volumes may
still contain those extension surfaces. Their retirement is an explicit
operator migration after the Python provider boundary and historical cleanup
script are authoritative.

`docker/postgres/migrations/retire_legacy_provider_extensions.sql` owns only the
database extension-removal step. It checks for every cron schedule and each
retired helper signature, applies a transaction-local five-second lock timeout,
and drops `http` and `pg_cron` with `RESTRICT` in one transaction. It never uses
`CASCADE`, never drops an application table or schema, and preserves
`gateway_retrieval_logs` when that evidence table exists.

The preflight intentionally treats a modified same-signature helper and an
unrelated cron job as operator-owned authority. Either condition blocks the
migration until an operator resolves it. An interrupted or failed attempt rolls
back; a successful attempt can be replayed idempotently.

This database migration does not remove operating-system packages and does not
edit `shared_preload_libraries`. Those host/image changes occur only after all
supported existing volumes have completed and verified the migration. See
[`docs/OPERABILITY.md`](docs/OPERABILITY.md) and the
[retirement ADR](docs/adr/legacy-postgresql-extension-retirement.md).

## Modular interoperability

CWL hosts such as `contextual-orchestrator` and `naruon` supply tenant context
only after their own authentication and authorization boundary. The package
does not require either host and retains standalone operation. When embedded,
tenant scope is a local control-plane identity and not model- or
provider-returned data.

## Verification boundary

Deterministic gates cover strict tenant validation, standalone compatibility,
tenant-qualified SQL parameters, current-state reconciliation, migration
idempotency, malformed database rows, default-deny policy text, schema
mirroring, operator documentation, and 100% production statement and branch
coverage. Live PostgreSQL isolation tests use a `NOSUPERUSER NOBYPASSRLS` role
and prove that identical provider identifiers in different tenants remain
independently addressable and mutually invisible when access occurs through the
trusted package boundary. They do not claim isolation after arbitrary SQL is
granted.

The extension-retirement gate additionally executes the real migration in the
bundled PostgreSQL image against historical package objects, substituted and
marker-preserving modified helpers, independent cron authority, and a preserved
application evidence table. Static contracts forbid `CASCADE`, table drops, and
schema drops; the live smoke executes the successful migration twice.
