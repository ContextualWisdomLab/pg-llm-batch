# Standalone Compose database-secret boundary

## Decision

The bundled standalone profile does not ship a shared PostgreSQL password. A deployment supplies `PG_LLM_BATCH_POSTGRES_PASSWORD` to Docker Compose, which creates one `postgres_password` secret and grants it explicitly to the `postgres` and `component` services.

The PostgreSQL container consumes the mount through `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password`. The component keeps `PG_LLM_BATCH_DSN` credential-free and starts through `python -m pg_llm_batch.compose_bootstrap --password-file /run/secrets/postgres_password`. The file path is not secret. Secret text is read with a finite 65,536-byte limit, strict UTF-8 decoding, non-empty enforcement, and rejection of NUL/CR/LF framing before psycopg constructs a private in-process conninfo value.

The password is therefore absent from committed Compose source, the configured component DSN, and process arguments. This does not claim that container memory is secret-free, that Docker secrets provide hardware-backed storage, or that an authorized container/runtime administrator cannot read mounted secret material.

## Rationale

Docker Compose defines top-level secrets as sensitive data sourced from a file or environment value and only grants a secret to services that explicitly request it. Docker's Compose guidance recommends secrets rather than ordinary service environment variables for sensitive values. The Docker Official Image for PostgreSQL documents the `_FILE` convention, including `POSTGRES_PASSWORD_FILE`, for mounted secrets.

PostgreSQL documents that password-bearing environment variables such as `PGPASSWORD` are not recommended because process-environment visibility varies by operating system. The component therefore does not copy the database password into its environment. Psycopg's conninfo builder receives the password as a separate field so characters such as colons, backslashes, spaces, and quotes do not require package-owned URI interpolation.

## Failure and recovery

The component fails closed before starting the health listener if the secret mount is missing, empty, oversized, not valid UTF-8, contains NUL/CR/LF framing, or if the credential-free bootstrap target cannot be converted into a valid psycopg conninfo value. Those failures use fixed package-owned `ConfigError` messages and intentionally suppress lower-layer exception chaining at the secret/conninfo boundary.

Operators recover by supplying a valid deployment secret and restarting the standalone profile. Rotation is a deployment operation: replace the source secret, recreate the affected containers so PostgreSQL and the component observe the same value, and verify readiness. This slice does not introduce automatic rotation, a cloud secret manager, or a durable secret store.

## Verification

`tests/test_compose_network_boundary.py` validates Docker Compose's normalized model and requires exactly one named secret for both services, PostgreSQL `_FILE` consumption, a credential-free component DSN, and a command line containing only the secret-file path.

`tests/test_compose_bootstrap.py` exercises bounded secret reads, missing/empty/oversized/malformed input, real psycopg quoting for special password characters, fixed error diagnostics, the in-process health handoff, argument parsing, and the actual module-entry path. The initial exact-source CI failure on the RED-only head proved the checked-in `POSTGRES_PASSWORD: pgllm` contract before production remediation.

## References

Docker, Inc. (2026). *Secrets*. Docker Docs. Retrieved August 12, 2026, from https://docs.docker.com/reference/compose-file/secrets/

Docker, Inc. (2026). *Manage secrets securely in Docker Compose*. Docker Docs. Retrieved August 12, 2026, from https://docs.docker.com/compose/how-tos/use-secrets/

Docker, Inc. (2026). *postgres—Official Image*. Docker Hub. Retrieved August 12, 2026, from https://hub.docker.com/_/postgres/

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Environment variables*. Retrieved August 12, 2026, from https://www.postgresql.org/docs/18/libpq-envars.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Database connection control functions*. Retrieved August 12, 2026, from https://www.postgresql.org/docs/18/libpq-connect.html
