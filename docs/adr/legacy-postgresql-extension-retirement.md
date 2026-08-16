# ADR: Fail-closed retirement of legacy PostgreSQL provider extensions

- **Status:** Proposed
- **Decision owner:** pg-llm-batch maintainers
- **Scope:** existing PostgreSQL volumes that still contain `http` or `pg_cron`

## Context

Fresh pg-llm-batch installations no longer grant PostgreSQL direct provider-network or independent scheduling authority. Existing volumes can still retain extension objects, the historical package schedule, operator schedules, or functions with the retired signatures. Removing those extensions with `CASCADE` would allow an operational cleanup to delete unreviewed dependent objects. `RESTRICT` is necessary but not sufficient to preserve extension members or objects explicitly marked `DEPENDS ON EXTENSION`: PostgreSQL removes those with the extension even without `CASCADE`. Treating a same-signature function, accidentally enrolled application table, or explicit extension-dependent routine as package-owned would therefore let migration code destroy operator state.

## Decision

1. Keep extension retirement in a separate operator-run migration after the historical package cleanup script.
2. Execute preflight and both extension drops in one PostgreSQL transaction.
3. Set a transaction-local five-second `lock_timeout` so operational contention fails visibly rather than waiting without bound.
4. Refuse retirement while any cron job remains, including operator-owned jobs.
5. Refuse retirement while any retired helper signature remains; exact or modified function ownership is resolved before this migration.
6. Inspect `pg_depend` and refuse every explicit auto-extension dependency (`deptype = 'x'`).
7. Refuse table-like extension members (`deptype = 'e'`) that are outside the expected `pg_cron` relations in the `cron` schema; in particular, `http` may not own an application table-like relation at the retirement boundary.
8. Use `DROP EXTENSION ... RESTRICT` only after those preservation guards pass. Never use `CASCADE`.
9. Preserve application-owned evidence, including `gateway_retrieval_logs` when present.
10. Make replay after success a no-op and require the same preflight after any failed or interrupted attempt.
11. Leave package removal and `shared_preload_libraries` changes to a later host/image change after all supported volumes have migrated.

## Consequences

The procedure is intentionally conservative. Operators must migrate unrelated cron jobs, investigate ambiguous helpers, detach application objects accidentally enrolled as extension members only after ownership review, and disposition explicit `DEPENDS ON EXTENSION` relationships before retirement. In return, extension-member and auto-extension semantics cannot silently convert cleanup into application-object deletion, and transaction failure leaves both extensions and application state at the prior committed boundary.

The migration is not a general extension manager, a rollback mechanism, or authority to remove operator-owned functions or dependencies. Restoring an extension or schedule requires an explicit reviewed recovery action or backup restoration. Removing a membership/dependency solely to bypass the preflight is outside this decision.

## Verification

- Static tests require the `pg_depend` `e`/`x` preservation guards and forbid `CASCADE`, table drops, and schema drops.
- The container smoke proves fail-closed behavior for unrelated schedules and modified helpers.
- The smoke temporarily enrolls `gateway_retrieval_logs` as an `http` extension member and proves retirement refuses while preserving the table and both extensions.
- The smoke marks an operator routine `DEPENDS ON EXTENSION http` and proves retirement refuses while preserving the routine and both extensions.
- The smoke proves `gateway_retrieval_logs` survives successful extension retirement after those fixture dependencies are explicitly removed.
- The migration is executed twice to prove idempotent replay.
- Operator guidance documents preflight, recovery, and rollback before this ADR can be accepted.
