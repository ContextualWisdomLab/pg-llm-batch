# Operation-owned PostgreSQL connection lifecycle

## Purpose

`pg-llm-batch` creates database-backed collaborators in two bounded operation surfaces:

- `PostgresBatchOrchestrator.prepare_batches()` creates a `PostgresConfigStore` and a `TokenCounter` for one preparation attempt; and
- one-shot CLI commands create configuration, secret, token-counting, and credential-provider collaborators for one command invocation.

`PostgresConfigStore` owns the connection used to read or update `com_config`. `SecretStore` owns the connection used for `com_secrets`. `TokenCounter` may cache a separate PostgreSQL connection for `pg_tiktoken` counting. These sessions are owned by the active operation, not by the caller. Each operation therefore provides **deterministic cleanup** on every exit path instead of relying on interpreter garbage collection or eventual object destruction.

## Store-constructor runtime contract

A database-backed store owns its PostgreSQL connection immediately after `psycopg.connect()` returns. `PostgresConfigStore` and `SecretStore` therefore protect every subsequent constructor step, including autocommit configuration, encryption setup, table creation, default insertion, and cache loading. If any setup failure occurs, the partially initialized store closes the connection it already acquired before re-raising the original failure.

This constructor cleanup is internal to the store and complements the outer orchestrator and CLI ownership rules. Callers never receive an unusable object, ordinary driver cleanup errors do not replace the primary setup failure, and successful construction retains the existing explicit `close()` contract. The change does not retry setup, hide the original database or encryption error, or convert a failed initialization into a usable fallback store.

`SecretStore` distinguishes intentional no-key local/development operation from an explicit encryption request. When no Fernet key is configured, the existing base64-obfuscated local/dev fallback remains available and is explicitly not encryption. When a **configured Fernet** key is supplied but the optional `cryptography` dependency is unavailable, construction **must fail closed** with `ConfigError` instead of silently downgrading the requested encryption to base64 obfuscation. Because this check runs inside the protected constructor setup block, the already acquired PostgreSQL connection is closed before the error propagates. Operators that configure a Fernet key must install the `secrets` extra (or otherwise provide the compatible `cryptography` dependency).

The no-key read path is also strict. Python's `base64.b64decode(..., validate=True)` rejects non-alphabet input instead of discarding it before the padding check. `SecretStore` uses that strict boundary and requires the decoded bytes to be valid UTF-8. Malformed stored base64 or invalid decoded text must **fail closed** as the bounded `ConfigError` message `stored secret encoding is invalid`; stored secret material and the decoder exception are not attached as exported cause or context.

## Orchestrator runtime contract

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

## CLI runtime contract

Every one-shot command closes the database-backed resources it creates:

- `config set` and `config get` close their `PostgresConfigStore` after success or failure;
- `config set-secret` closes its `SecretStore` after success or failure;
- `count-tokens` closes `TokenCounter` before closing the configuration store, including when token counting raises; and
- submit, poll, wait, and retrieve use an async context manager that closes the HTTP client first, then `SecretStore`, then `PostgresConfigStore`.

The async client context uses nested `try/finally` ownership. If secret-store construction fails, the completed configuration store is still closed. If provider or HTTP-client construction fails, both completed database stores are closed. If the remote operation or HTTP-client shutdown raises, the database-store cleanup still runs in reverse construction order.

The CLI keeps the existing command output, exit-code, credential lookup, and endpoint behavior. Cleanup is not exposed as a new user-facing command or protocol.

## Transaction and compatibility boundary

This change does not alter the existing short-lived query and persistence transaction contexts. Psycopg connection context managers continue to own their commit, rollback, and close behavior. The explicit lifecycle rule applies to collaborators constructed outside those contexts that previously had no deterministic release path.

The change introduces no connection pool, schema migration, table change, credential format, provider request, token-counting algorithm, payload format, public API, or cross-service dependency. `pg-llm-batch` remains independently deployable and embeddable.

## Operational rationale

Psycopg documents a `Connection` as a database session and states that code using an un-entered connection is responsible for calling `commit()`, `rollback()`, and `close()` where needed. It also documents context-manager use as the normal mechanism for closing resources at block exit. The package follows the same explicit-lifecycle principle for its cached token-counting connection, database-backed configuration store, and secret store.

Python documents `finally` as the cleanup clause that executes when control leaves the protected block, including when the block returns or raises. Nested `try/finally` therefore makes the ownership order reviewable and deterministic across successful preparation, command completion, assembly failure, remote-operation failure, partial collaborator construction, and store-constructor setup failure.

Python's Base64 library documents that `b64decode(..., validate=False)` discards non-alphabet characters before padding validation, while `validate=True` raises `binascii.Error` for them. The stored-secret boundary uses strict validation because accepting and normalizing corrupted persistence would make database corruption indistinguishable from a valid credential.

## Verification

Deterministic tests prove that:

1. successful preparation closes the token counter and configuration store;
2. assembly failure closes both owned collaborators before the original error propagates;
3. configuration-store cleanup still occurs when `TokenCounter` construction fails;
4. `TokenCounter.close()` releases the cached connection once and is safe to call again;
5. a driver close failure still clears the cached connection reference;
6. invalid configuration is rejected before `pg_tiktoken` connection acquisition;
7. existing runtime-limit test doubles implement and verify the same cleanup contract;
8. one-shot config and secret commands close their owned stores;
9. successful and failed token-count commands close the counter before the configuration store;
10. async client exit closes HTTP, secret, and configuration resources in reverse construction order;
11. partial async credential construction closes every successfully constructed owner;
12. `PostgresConfigStore` closes its acquired connection when constructor setup fails;
13. `SecretStore` closes its acquired connection when constructor setup fails;
14. a configured Fernet key with unavailable `cryptography` must fail closed instead of entering the no-key base64 fallback; and
15. malformed no-key base64 persistence must fail closed with bounded diagnostics and no stored material in exception cause or context.

The complete gate must continue to prove Python 3.10, 3.12, and 3.14 behavior; 100% production statement and branch coverage; 100% public docstrings; compilation; Ruff; lock freshness; package construction; Compose validation; container builds; Security Scan; and SAST.

## Operator recovery

If database sessions remain unexpectedly active after this change, identify whether they belong to:

- the configuration store;
- the secret store;
- the token-counting cache;
- an active short-lived query context;
- an active persistence transaction;
- a currently running CLI remote operation; or
- embedding code outside the bounded orchestrator and CLI operations that independently owns a `TokenCounter` or store.

Call `TokenCounter.close()`, `PostgresConfigStore.close()`, or `SecretStore.close()` when custom embedding code creates those objects with a longer lifetime. A store constructor that raises does not return an owner to close; its internal failure path must already have released the acquired connection. Do not add a global connection singleton or suppress constructor validation to reduce connection churn. If sustained throughput requires pooling, design it as a separate reviewed ownership contract with bounded capacity, transaction-state reset, health checks, tenant isolation, shutdown behavior, and rollback evidence.

If a configured Fernet key fails because `cryptography` is unavailable, install the package's `secrets` extra or the governed compatible cryptography dependency and retry with the same intended key. Do not remove the key merely to bypass the failure in a production environment; doing so selects the explicitly weaker local/dev base64-obfuscation mode.

If a stored local/dev obfuscated value fails strict Base64 or UTF-8 validation, treat the row as corrupted evidence. Do not trim, discard, or normalize bytes to make the credential usable. Restore the value from a trusted source through the normal `SecretStore` write path, or rotate the affected credential, then retry.

## Rollback

There is no persistent data or migration to reverse. Code **rollback** is mechanically straightforward, but it restores nondeterministic release of orchestrator-owned, CLI-owned, and partially initialized store sessions, reacquires the token-counting connection before configuration validation, would restore silent encryption downgrade when a configured Fernet key cannot be honored, and would again permit non-alphabet Base64 characters to be discarded during local/dev credential reads. During an incident, retain the explicit lifecycle and fail-closed encryption/decoding boundaries and diagnose the failing connection, dependency, persistence, or driver cleanup path rather than removing `try/finally`, constructor cleanup, strict Base64 validation, or relying on garbage collection.

## References

Psycopg Team. (2026). *Basic module usage*. Psycopg 3 documentation. https://www.psycopg.org/psycopg3/docs/basic/usage.html

Python Software Foundation. (2026). *Base16, Base32, Base64, Base85 data encodings*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/base64.html

Python Software Foundation. (2026). *Compound statements*. Python 3.14.6 documentation. https://docs.python.org/3/reference/compound_stmts.html
