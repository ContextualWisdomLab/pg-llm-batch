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

For a **new disposable Compose project**, generate a development-only database password once, retain it in your normal local secret store, and reuse that same value for later starts of the existing `pgdata` volume. PostgreSQL applies the initialization password only when it first creates the data directory; changing the Compose secret later does not rotate the existing database role password.

Create a mode-0600 libpq passfile for host-side CLI access so the password is not embedded in `PG_LLM_BATCH_DSN`. The passfile writer escapes libpq delimiters before Compose consumes the bootstrap environment secret.

```bash
export PG_LLM_BATCH_POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Save this generated value outside the repository in your local secret manager.
export PGPASSFILE="$(mktemp "${TMPDIR:-/tmp}/pg-llm-batch.pgpass.XXXXXX")"
chmod 600 "$PGPASSFILE"
python - <<'PY'
import os
from pathlib import Path

password = os.environ["PG_LLM_BATCH_POSTGRES_PASSWORD"]
escaped = password.replace("\\", "\\\\").replace(":", "\\:")
Path(os.environ["PGPASSFILE"]).write_text(
    f"localhost:5432:pgllm:pgllm:{escaped}\n",
    encoding="utf-8",
)
PY

docker compose up -d --build
unset PG_LLM_BATCH_POSTGRES_PASSWORD
export PG_LLM_BATCH_DSN="postgresql://pgllm@localhost:5432/pgllm"
python -m pg_llm_batch init-db
python -m pg_llm_batch health
```

For subsequent starts that reuse the same `pgdata` volume, restore the **same** development password from your local secret manager, recreate the mode-0600 passfile with the same escaping step, run `docker compose up`, and unset `PG_LLM_BATCH_POSTGRES_PASSWORD` again. The CLI then uses the credential-free DSN plus `PGPASSFILE`. Changing only the Compose secret does not rotate the existing database role password.

If this is a disposable development database and the original password is intentionally unavailable, `docker compose down -v` removes the persisted database volume; the next start is a new initialization and permanently deletes the old local database contents. For a retained database, rotate the PostgreSQL role credential deliberately and update the Compose/application secret together instead of changing only the environment value.

Remove the temporary passfile when the local CLI session ends:

```bash
rm -f "$PGPASSFILE"
unset PGPASSFILE PG_LLM_BATCH_DSN
```

Do not use a shared example password. Production deployments should supply database credentials through their reviewed secret-management and rotation path.

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
