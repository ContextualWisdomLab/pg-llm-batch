# pg-llm-batch

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/pg-llm-batch)

`pg-llm-batch` is a standalone and embeddable PostgreSQL-backed engine for token-aware LLM batch preparation, submission, polling, retrieval, and durable lifecycle evidence.

## Product responsibility

- Count model tokens authoritatively inside PostgreSQL with `pg_tiktoken`.
- Assemble JSONL batches under explicit token, byte, and record limits.
- Submit, poll, wait for, and retrieve provider batches behind the package's validated provider boundary.
- Persist standalone or tenant-scoped lifecycle state with default-deny PostgreSQL row-level security.
- Keep PostgreSQL client authority behind `PostgresDriverPort` instead of spreading concrete-driver behavior across bounded contexts.
- Expose bounded health/readiness, recovery, reconciliation, and optional OpenTelemetry operations without turning provider/prompt content into ordinary evidence.

## Commercial dependency status

On the current Draft driver-migration stack, the default runtime manifest pins exact `pg8000==1.31.5`. Psycopg is retained only in optional test/development dependencies for legacy-adapter parity. That branch state is materially beyond protected `main`, but it is not shipped commercial authority.

[Issue #322](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/322) remains open until the driver transition is normally integrated and an exact protected release head re-proves package/license/vulnerability/SBOM/provenance/reproducibility/rollback evidence. Passing Draft tests do not substitute for protected integration or immutable release evidence.

A separate buyer-visible security gap remains in [issue #123](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/123): package-created remote PostgreSQL connections on this Draft do not yet prove mandatory encrypted transport plus authenticated server identity. Loopback Compose verification must not be generalized into a secure-remote claim.

## Development quick start

The bundled Compose profile mounts the PostgreSQL password as a named secret and binds host ports to loopback by default:

```bash
export PG_LLM_BATCH_POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Retain this value outside the repository for the life of the disposable pgdata volume.
docker compose up -d --build
curl -fsS localhost:8080/healthz
```

The component uses a credential-free bootstrap target plus the mounted password; `compose_bootstrap` combines them only in process memory through the selected PostgreSQL driver.

The retained pg8000 runtime does not inherit libpq `PGPASSFILE` semantics. Host-side CLI development therefore must not reuse the old Psycopg pattern that paired a credential-free DSN with `PGPASSFILE`. For a loopback-only local shell, construct `PG_LLM_BATCH_DSN` from the locally retained password in environment state rather than argv, run the needed commands, and unset it afterwards. This is a development compatibility path, not the secure-remote production contract. See [bootstrap source precedence](doctoring/bootstrap-dsn-precedence.md) and the repository README for the exact example and security boundary.

Do not use a shared example password. Reusing an existing `pgdata` volume requires the actual persisted database-role credential unless it is deliberately rotated inside PostgreSQL. `docker compose down -v` permanently deletes a disposable local database volume.

## Architecture

PostgreSQL owns authoritative token accounting and package-owned durable lifecycle state. Python owns validated provider-facing I/O and orchestration. Shared-table hosts bind tenant scope from trusted host authorization context and rely on forced RLS; provider metadata never selects tenant identity.

The current Draft runtime selects exact pg8000 behind `PostgresDriverPort`. Psycopg remains only optional legacy-adapter test evidence. Unsupported libpq connection semantics fail closed at the pg8000 anti-corruption boundary rather than being silently approximated.

Key references:

- [Remote batch lifecycle](remote-batch-lifecycle.md)
- [Tenant-scoped lifecycle](doctoring/tenant-scoped-lifecycle.md)
- [Bootstrap DSN precedence and argv confidentiality](doctoring/bootstrap-dsn-precedence.md)
- [CLI secret input](doctoring/cli-secret-input.md)
- [Count-tokens stdin privacy](doctoring/count-tokens-stdin-privacy.md)
- [OpenTelemetry operations](doctoring/opentelemetry-operations.md)

## Releases and verification

Use protected-branch history, GitHub Releases, current checks, and exact-source repository evidence to determine what is shipped. A documentation source commit is not evidence that GitHub Pages is published, and a green Draft is not evidence that a dependency migration is commercially released.

Commercial driver readiness requires #322 to reach protected release authority with a clean final dependency/license/vulnerability/SBOM/provenance/reproducibility/rollback chain. Secure remote PostgreSQL transport remains independently owned by #123.

- [Repository](https://github.com/ContextualWisdomLab/pg-llm-batch)
- [README](https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/README.md)
- [Apache-2.0 source license](https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/LICENSE)
- [Commercial dependency transition #322](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/322)
- [PostgreSQL transport-security gap #123](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/123)
- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/pg-llm-batch)
