# pg-llm-batch

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/pg-llm-batch)

`pg-llm-batch` is a standalone and embeddable PostgreSQL-backed engine for token-aware LLM batch preparation, submission, polling, retrieval, and durable lifecycle evidence.

## Product responsibility

- Count model tokens authoritatively inside PostgreSQL with `pg_tiktoken`.
- Assemble OpenAI-compatible JSONL batches under explicit token, byte, and record limits.
- Submit, poll, wait for, and retrieve batches through OpenAI-compatible Batch APIs.
- Persist standalone or tenant-scoped lifecycle state with default-deny PostgreSQL row-level security.
- Keep configuration and encrypted secrets in PostgreSQL-backed stores rather than ordinary runtime environment variables.
- Expose bounded health/readiness, recovery, and optional OpenTelemetry operations without leaking prompt/provider content into telemetry.

## Commercial dependency status

The repository's original source is Apache-2.0, but the current runtime manifest directly depends on `psycopg[binary]>=3.1`. Current Psycopg/Psycopg Binary package metadata identifies that path as LGPL-3.0-only, which is outside ContextualWisdomLab's commercial inbound baseline. [Issue #322](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/322) owns replacement while preserving PostgreSQL transaction, RLS, type-adaptation, concurrency, recovery, packaging, and integration behavior.

The current compose/install commands document development and verification of today's implementation; they are not evidence that the dependency graph is approved for commercial incorporation or distribution. The Apache-2.0 repository grant does not relicense Psycopg.

## Development quick start

Create a fresh development-only database password for this run. Docker Compose consumes the value through its named `postgres_password` secret, and the same generated value is used only as bootstrap transport for the local CLI DSN.

```bash
export PG_LLM_BATCH_POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose up -d --build
export PG_LLM_BATCH_DSN="postgresql://pgllm:${PG_LLM_BATCH_POSTGRES_PASSWORD}@localhost:5432/pgllm"
python -m pg_llm_batch init-db
python -m pg_llm_batch health
```

Do not replace the generated value with a shared example password. Production deployments should supply the Compose secret and application bootstrap credential through their reviewed secret-management path.

Use the [repository README](https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/README.md) for gateway configuration, secret input, batch submission, durable lifecycle modes, the currently blocked embedding path, recovery, observability, and test instructions.

## Architecture

PostgreSQL owns authoritative token counting and package-owned lifecycle state. Python owns validated provider-facing I/O and orchestration. Shared-table hosts bind tenant scope from trusted host authorization context and rely on forced RLS; provider metadata never selects tenant identity.

Key references:

- [Remote batch lifecycle](remote-batch-lifecycle.md)
- [Tenant-scoped lifecycle](doctoring/tenant-scoped-lifecycle.md)
- [CLI secret input](doctoring/cli-secret-input.md)
- [Count-tokens stdin privacy](doctoring/count-tokens-stdin-privacy.md)
- [OpenTelemetry operations](doctoring/opentelemetry-operations.md)

## Releases and verification

Use protected-branch history, GitHub Releases, current checks, and repository test evidence to determine what is shipped. A documentation source commit is not evidence that GitHub Pages is already published; Pages completion requires live repository settings and HTTPS content verification after reconciliation.

Commercial-readiness evidence additionally requires issue #322 to be resolved with a dependency graph that no longer contains a disallowed GPL/LGPL/AGPL-family runtime package. Passing product tests do not override that license boundary.

- [Repository](https://github.com/ContextualWisdomLab/pg-llm-batch)
- [README](https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/README.md)
- [Apache-2.0 source license](https://github.com/ContextualWisdomLab/pg-llm-batch/blob/main/LICENSE)
- [Commercial dependency blocker #322](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/322)
- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/pg-llm-batch)
