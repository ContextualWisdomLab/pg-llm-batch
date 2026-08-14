# ADR: Fail-closed retirement of legacy PostgreSQL provider extensions

- **Status:** Proposed
- **Decision owner:** pg-llm-batch maintainers
- **Scope:** existing PostgreSQL volumes that still contain `http` or `pg_cron`

## Context

Fresh pg-llm-batch installations no longer grant PostgreSQL direct provider-network or independent scheduling authority. Existing volumes can still retain extension objects, the historical package schedule, operator schedules, or functions with the retired signatures. Removing those extensions with `CASCADE` would allow an operational cleanup to delete unreviewed dependent objects. Treating a same-signature function as package-owned would also let migration code destroy an operator-modified object.

## Decision

1. Keep extension retirement in a separate operator-run migration after the historical package cleanup script.
2. Execute preflight and both extension drops in one PostgreSQL transaction.
3. set a transaction-local five-second `lock_timeout` so operational contention fails visibly rather than waiting without bound.
4. Refuse retirement while any cron job remains, including operator-owned jobs.
5. Refuse retirement while any retired helper signature remains; exact or modified function ownership is resolved before this migration.
6. Use `DROP EXTENSION ... RESTRICT` only. Never use `CASCADE`.
7. Preserve application-owned evidence, including `gateway_retrieval_logs` when present.
8. Make replay after success a no-op and require the same preflight after any failed or interrupted attempt.
9. Leave package removal and `shared_preload_libraries` changes to a later host/image change after all supported volumes have migrated.

## Consequences

The procedure is intentionally conservative. Operators must migrate unrelated cron jobs and investigate ambiguous helpers before retirement. In return, the database never silently converts a cleanup into destructive dependency removal, and transaction failure leaves both extensions and application state at the prior committed boundary.

The migration is not a general extension manager, a rollback mechanism, or authority to remove operator-owned functions. Restoring an extension or schedule requires an explicit reviewed recovery action or backup restoration.

## Verification

- Static tests forbid `CASCADE`, table drops, and schema drops.
- The container smoke proves fail-closed behavior for unrelated schedules and modified helpers.
- The smoke proves `gateway_retrieval_logs` survives extension retirement.
- The migration is executed twice to prove idempotent replay.
- Operator guidance documents preflight, recovery, and rollback before this ADR can be accepted.
