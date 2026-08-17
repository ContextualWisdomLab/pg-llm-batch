# ADR 0007: Durable tenant-isolated result checkpoint store

- **Status:** Accepted
- **Date:** 2026-08-14
- **Decision owners:** ContextualWisdomLab maintainers
- **Depends on:** ADR 0006 and the resumable checkpoint implementation

## Context

ADR 0006 defines immutable prefix checkpoints but deliberately leaves durable
storage, rollback protection, tenant separation, consumer concurrency, and
coordination with record effects to the embedding host. Requiring every buyer or
CWL host to recreate those controls independently produces inconsistent recovery
semantics and weak acquisition evidence.

The package needs one optional PostgreSQL implementation that remains standalone,
can be embedded in a modular MSA, and does not change the existing streaming API.
It must preserve the checkpoint's prefix-only assurance boundary: successful
reproduction does not establish full-stream immutability for an unseen suffix.

## Decision

Provide `PostgresBatchResultCheckpointStore` and the
`llm_result_stream_checkpoints` table. Durable identity is:

```text
(tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id)
```

The consumer name is a trusted host-selected logical processor identity, not
provider or model output. All identity fields are strictly validated before SQL.
The table stores the complete validated `BatchResultCheckpoint`, not a partial
cursor or decoded record body.

### Compare-and-swap

Every advancement reads the current row with `SELECT ... FOR UPDATE`. A changed
row requires the caller's exact `expected_previous` checkpoint. Both
`record_count` and `batch_line_count` must increase. An exact repeat is
idempotent; missing, stale, forked, or regressive state raises a bounded
`CheckpointConflictError` without overwrite.

A row lock cannot protect a key that does not yet exist. Initial creation uses
`INSERT ... ON CONFLICT ... DO NOTHING RETURNING`. A losing writer re-reads the
committed row with `FOR UPDATE`: an identical checkpoint is an idempotent
success; a different checkpoint fails closed as an initial-writer conflict.

### Transaction ownership

`save()` and `load()` use package-owned transactions for simple standalone use.
`save_in_transaction()` and `load_in_transaction()` accept a caller-owned cursor
and never commit or roll back it. A host can therefore apply local record effects
and advance the checkpoint in the same PostgreSQL transaction.

This is not a distributed exactly-once protocol. Side effects in another
database, queue, object store, or external API still require an idempotency key,
transactional outbox, or separately proven reconciliation protocol.

### Tenant isolation

The migration enables and forces PostgreSQL row-level security. Package store
operations bind a validated host-authorized tenant scope with transaction-local
`set_config` and include tenant scope in every key predicate as defense in depth.
Application roles must be `NOSUPERUSER NOBYPASSRLS` and must not expose arbitrary
SQL to tenants. RLS is not authentication, authorization, or SQL-injection
prevention; the embedding host remains responsible for mapping authenticated
callers to the correct trusted tenant scope.

### Database target authority

Package-owned store construction and schema installation require an explicit
nonblank PostgreSQL DSN. Missing or blank authority fails before Psycopg connects,
so ambient libpq environment or service-file defaults cannot silently select the
checkpoint database. Caller-owned cursors remain the embedding host's database
authority boundary.

### Migration and rollback

The package and bundled-container migrations are byte-identical. The deployable
PostgreSQL image installs the checkpoint migration after its existing schema and
legacy-retrieval initialization steps. Database object names use descriptive
snake_case names.

The rollback migration refuses to drop a non-empty checkpoint table. Because
forced RLS without a tenant setting would hide acknowledgement rows from an
ordinary query, rollback uses one atomic PostgreSQL block: it temporarily removes
`FORCE ROW LEVEL SECURITY`, performs an owner-visible emptiness check, and raises
SQLSTATE 55000 if any acknowledgement exists. The exception aborts the same
transaction, restoring forced RLS automatically. A role lacking owner authority
cannot relax RLS or reach the destructive drop.

## Alternatives considered

### Keep persistence entirely host-owned

Rejected as the only supported path because it duplicates subtle concurrency,
RLS, migration, and rollback logic in every integration. Host-owned stores remain
allowed behind the immutable checkpoint contract.

### Update without `expected_previous`

Rejected because last-writer-wins can silently move a consumer to a forked
provider prefix or overwrite a newer acknowledgement.

### Rely only on a unique constraint for first-writer concurrency

Rejected because a raw uniqueness failure is not a stable operator contract and
cannot distinguish an identical idempotent race from a conflicting first
checkpoint.

### Check rollback emptiness under forced RLS

Rejected because a missing tenant setting can produce a false empty result and
silently authorize destructive evidence loss.

### Claim whole-stream or exactly-once assurance

Rejected. The checkpoint authenticates neither the provider nor its unseen
suffix, and PostgreSQL atomicity does not extend to external side effects.

## Consequences

- Restart recovery has a package-owned durable path with explicit tenant and
  consumer identity.
- Local PostgreSQL effects can share one caller-owned transaction with checkpoint
  advancement.
- Competing writers receive deterministic bounded conflicts instead of silent
  overwrite.
- Fresh bundled PostgreSQL databases install the checkpoint schema by default.
- Operators must use non-bypass application roles and preserve trusted tenant
  selection outside provider/request content.
- Destructive rollback requires table-owner authority and an owner-visible empty
  table; non-empty evidence aborts and restores forced RLS.
- Full-stream immutability, distributed exactly-once delivery, checkpoint-store
  authentication, and administrative rollback authorization remain explicit host
  responsibilities.

## Verification

Unit and live PostgreSQL acceptance cover strict target/tenant/consumer
validation, package and caller-owned transactions, exact compare-and-swap,
idempotent and conflicting concurrent first writers, stale-writer refusal,
forced-RLS tenant isolation, bundled-image schema installation, empty rollback,
and fail-closed non-empty rollback. Repository quality gates additionally require
Python 3.10/3.12/3.14, exact owned production statement/branch coverage, public
docstrings, package/container validation, security/SAST, and release acceptance
on the unchanged integration head.

## References

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation:
Explicit locking*. https://www.postgresql.org/docs/18/explicit-locking.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Row
security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html
