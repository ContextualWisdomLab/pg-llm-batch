# Orchestrator-owned PostgreSQL connection lifecycle

## Purpose

`PostgresBatchOrchestrator.prepare_batches()` creates two collaborators for one preparation attempt:

- `PostgresConfigStore`, which owns the connection used to read `com_config`; and
- `TokenCounter`, which may cache a separate PostgreSQL connection for `pg_tiktoken` counting.

Those sessions are owned by the preparation call, not by the caller. The call therefore provides **deterministic cleanup** on every exit path instead of relying on interpreter garbage collection or eventual object destruction.

## Runtime contract

The orchestrator uses nested `try/finally` blocks with the following ownership order:

1. construct `PostgresConfigStore`;
2. construct `TokenCounter` with that store;
3. apply an optional stricter runtime token limit;
4. assemble and persist the payloads;
5. close `TokenCounter`; and
6. close `PostgresConfigStore`.

`TokenCounter` is closed before its configuration store because it is the inner dependent collaborator. The outer `finally` still closes `PostgresConfigStore` if `TokenCounter` construction fails, so partial construction does not retain the configuration session.

`TokenCounter.close()` clears its cached connection reference before asking the database driver to close the session. The method is idempotent. If ordinary driver cleanup raises, the unusable connection is not retained and cleanup does not replace the primary orchestration result or failure with a secondary close error.

The constructor completes **configuration validation before** it attempts `pg_tiktoken` extension setup or cached connection acquisition. Invalid `buffer_percentage` input therefore fails at the declared validation boundary without opening a token-counting database session.

## Transaction and compatibility boundary

This change does not alter the existing short-lived query and persistence transaction contexts. Psycopg connection context managers continue to own their commit, rollback, and close behavior. The new lifecycle rule applies only to the longer-lived collaborators that were constructed outside those contexts and previously had no deterministic release path.

The change introduces no connection pool, schema migration, table change, credential, provider request, token-counting algorithm, payload format, public API, or cross-service dependency. `pg-llm-batch` remains independently deployable and embeddable.

## Operational rationale

Psycopg documents a `Connection` as a database session and states that code using an un-entered connection is responsible for calling `commit()`, `rollback()`, and `close()` where needed. It also documents context-manager use as the normal mechanism for closing resources at block exit. The package follows the same explicit-lifecycle principle for its cached token-counting connection and its database-backed configuration store.

Python documents `finally` as the cleanup clause that executes when control leaves the protected block, including when the block returns or raises. Nested `try/finally` therefore makes the ownership order reviewable and deterministic across successful preparation, assembly failure, persistence failure, and partial collaborator construction.

## Verification

Deterministic tests prove that:

1. successful preparation closes the token counter and configuration store;
2. assembly failure closes both owned collaborators before the original error propagates;
3. configuration-store cleanup still occurs when `TokenCounter` construction fails;
4. `TokenCounter.close()` releases the cached connection once and is safe to call again;
5. a driver close failure still clears the cached connection reference;
6. invalid configuration is rejected before `pg_tiktoken` connection acquisition; and
7. existing runtime-limit test doubles implement and verify the same cleanup contract.

The complete gate must continue to prove Python 3.10, 3.12, and 3.14 behavior; 100% production statement and branch coverage; 100% public docstrings; compilation; Ruff; lock freshness; package construction; Compose validation; container builds; Security Scan; and SAST.

## Operator recovery

If database sessions remain unexpectedly active after this change, identify whether they belong to:

- the configuration store;
- the token-counting cache;
- an active short-lived query context;
- an active persistence transaction; or
- code outside `prepare_batches()` that independently owns a `TokenCounter`.

Call `TokenCounter.close()` when custom embedding code creates a counter with a lifetime longer than one operation. Do not add a global connection singleton or suppress constructor validation to reduce connection churn. If sustained throughput requires pooling, design it as a separate reviewed ownership contract with bounded capacity, transaction-state reset, health checks, tenant isolation, shutdown behavior, and rollback evidence.

## Rollback

There is no persistent data or migration to reverse. Code **rollback** is mechanically straightforward, but it restores nondeterministic release of the two orchestrator-owned sessions and reacquires the token-counting connection before configuration validation. During an incident, retain the explicit lifecycle and diagnose the failing connection or driver cleanup path rather than removing `try/finally` or relying on garbage collection.

## References

Psycopg Team. (2026). *Basic module usage*. Psycopg 3 documentation. https://www.psycopg.org/psycopg3/docs/basic/usage.html

Python Software Foundation. (2026). *Compound statements*. Python 3.14.6 documentation. https://docs.python.org/3/reference/compound_stmts.html
