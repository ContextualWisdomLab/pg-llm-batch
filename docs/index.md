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

## Quick start

```bash
docker compose up -d --build
export PG_LLM_BATCH_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm
python -m pg_llm_batch init-db
python -m pg_llm_batch health
```

Use the [repository README](../README.md) for gateway configuration, secret input, batch submission, durable lifecycle modes, embedding as a submodule, recovery, observability, and test instructions.

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

- [Repository](https://github.com/ContextualWisdomLab/pg-llm-batch)
- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/pg-llm-batch)
