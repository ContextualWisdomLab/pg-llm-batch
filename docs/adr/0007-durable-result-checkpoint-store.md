# ADR 0007: Durable tenant-isolated result checkpoint store

- **Status: Accepted**
- **Date:** 2026-08-06
- **Decision owners:** ContextualWisdomLab maintainers
- **Depends on:** ADR 0006 and the resumable checkpoint implementation

## Context

ADR 0006 defines immutable prefix checkpoints, but deliberately leaves durable
storage, rollback protection, tenant separation, consumer concurrency, and
coordination with record effects to the embedding host. Requiring every buyer or
CWL host to recreate those controls independently produces inconsistent recovery
semantics and weak acquisition evidence.

The package needs one optional PostgreSQL implementation that remains standalone,
can be embedded in a modular MSA, and does not change the existing streaming API.
It must preserve the checkpoint's prefix-only assurance boundary: successful
reproduction does not establish full-stream immutability for an unseen suffix.

## Decision

Add `PostgresBatchResultCheckpointStore` and the
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

A row lock cannot protect a key that does not yet exist. Initial creation
therefore uses `INSERT ... ON CONFLICT ... DO NOTHING RETURNING`. A losing writer
re-reads the committed row with `FOR UPDATE`: an identical checkpoint is an
idempotent success, a different checkpoint is `initial_checkpoint_race`, and a
conflict without a visible row fails closed as database inconsistency.

### Transaction ownership

`save()` and `load()` use package-owned transactions for simple standalone use.
`save_in_transaction()` and `load_in_transaction()` accept a caller-owned cursor
and never commit or roll back it. A host can therefore apply local record effects
and advance the checkpoint in the same PostgreSQL transaction.

This is not a distributed exactly-once protocol. Side effects in another
database, queue, object store, or external API still require an idempotency key,
transactional outbox, or separately proven reconciliation protocol.

### Tenant isolation

The migration enables and forces PostgreSQL row-level security. The package binds
a validated host-authorized tenant scope with transaction-local `set_config` and
also includes tenant scope in every key predicate as defense in depth.
Application roles must be `NOSUPERUSER NOBYPASSRLS` and must not expose arbitrary
SQL to tenants. RLS is not authentication, authorization, or SQL-injection
prevention; a role permitted to execute arbitrary SQL can choose another setting.

### Migration and rollback

The package and container migrations are byte-identical. Database object names
contain at least two descriptive words and use snake_case. The rollback migration
refuses to drop a non-empty checkpoint table, requiring export or explicit
operator reconciliation before evidence can be erased.

## Alternatives considered

### Keep persistence entirely host-owned

Rejected as the only supported path because it duplicates subtle concurrency,
RLS, migration, and rollback logic in every integration. Host-owned stores remain
allowed behind the immutable checkpoint contract.

### Update without `expected_previous`

Rejected because last-writer-wins can silently move a consumer to a forked
provider prefix or overwrite a newer acknowledgement.

### Rely only on a unique constraint for first-writer concurrency

Rejected because an unclassified database uniqueness exception is not a stable
operator contract and cannot distinguish an identical idempotent race from a
conflicting first checkpoint.

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
- Operators must apply the dedicated migration and use non-bypass application
  roles.
- Full-stream immutability, distributed exactly-once delivery, checkpoint-store
  authentication, and administrative rollback authorization remain explicit host
  responsibilities.
