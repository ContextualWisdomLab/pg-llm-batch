# pg-llm-batch

Standalone **and** embeddable Postgres LLM batch engine. It counts tokens
**inside** PostgreSQL with [`pg_tiktoken`](https://github.com/postgresml/pg_tiktoken),
assembles OpenAI-compatible JSONL batches under token/byte/record limits, and
submits/polls/retrieves them against any OpenAI-compatible Batch API (OpenAI,
Azure OpenAI, or a LiteLLM gateway).

Extracted from ContextualWisdomLab's `xtrmLLMBatchPython` batch core and
relicensed to **Apache-2.0** (see [`NOTICE`](NOTICE) for provenance).

## Why it exists

- **Token counting is authoritative.** Counts come from `pg_tiktoken` in the
  database, so the numbers used to pack a batch are exactly what the DB sees —
  there is no drifting Python-side tokenizer.
- **No secrets in the environment.** All configuration and credentials live in
  Postgres KV tables (`com_config`, `com_secrets`). The environment is only a
  *bootstrap transport* for the DSN and an optional Fernet key. This replaces
  the ~75 `os.getenv` reads in the upstream app.
- **Disk-free assembly.** JSONL payloads are stored as `JSONB` and reconstructed
  by JOIN, never written to disk.

## Architecture

```
llm_requests ──▶ PostgresBatchOrchestrator.prepare_batches()
                     │  (TokenCounter → pg_tiktoken, BatchAccumulator)
                     ▼
   llm_batch_file_payloads (JSONB)  +  llm_batch_files  +  llm_jsonl_lines
                     │
                     ▼
        BatchAPIClient.upload_jsonl → create_batch_job → get_batch_status → download_results
                     │
   (or) pg_cron job  cron_fetch_batch_results()  polls + imports results via pgsql-http
```

| Piece | Module |
| --- | --- |
| Token counting + accumulation | `pg_llm_batch/token_counter.py` |
| Batch assembly + persistence | `pg_llm_batch/orchestrator.py` |
| Submit / poll / retrieve | `pg_llm_batch/batch_api_client.py` |
| KV config + encrypted secrets | `pg_llm_batch/config.py` |
| DDL subset | `pg_llm_batch/schema.sql` |
| Readiness (`/healthz`) | `pg_llm_batch/health.py` |
| CLI | `pg_llm_batch/cli.py` |

## Requirements

- PostgreSQL with `pg_tiktoken`, `pg_cron`, and `http` (pgsql-http). The bundled
  image (`docker/postgres/Dockerfile`) builds all three.
- Python 3.9+ with `psycopg[binary]` and `aiohttp` (installed via `pip install .`).

---

## Standalone use

### 1. Bring up the stack

```bash
docker compose up -d --build
# postgres becomes healthy only once pg_tiktoken + com_config are ready;
# the component then serves GET /healthz on :8080
curl -fsS localhost:8080/healthz
```

### 2. Point it at your gateway (config + secret in the DB, not env)

```bash
export PG_LLM_BATCH_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm
python -m pg_llm_batch init-db                                   # idempotent
python -m pg_llm_batch config set gateway base_url https://your-gateway/v1
python -m pg_llm_batch config set-secret gateway_api_key.default sk-your-key
```

Encrypt secrets at rest by exporting a Fernet key as bootstrap transport:

```bash
export PG_LLM_BATCH_SECRET_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
python -m pg_llm_batch config set-secret gateway_api_key.default sk-your-key
```

### 3. Count, submit, poll, retrieve

```bash
python -m pg_llm_batch count-tokens --model gpt-4o --text "hello world"
# {"model": "gpt-4o", "tokens": 2}

# after prepare_batches() has produced a memory://<file_id> payload:
python -m pg_llm_batch submit  --endpoint default --file-path memory://<file_id>
python -m pg_llm_batch poll     --endpoint default --batch-id  <batch_id>
python -m pg_llm_batch retrieve --endpoint default --batch-id  <batch_id>
```

Assemble a batch programmatically:

```python
from pg_llm_batch import PostgresBatchOrchestrator

orch = PostgresBatchOrchestrator("postgresql://pgllm:pgllm@localhost:5432/pgllm")
result = orch.prepare_batches(batch_uuid="<uuid or input_file_path>")
for payload in result["ready"]:
    print(payload.file_path, payload.request_count, payload.total_tokens)
```

### Health / readiness

`GET /healthz` returns `200` when the database, `pg_tiktoken`, and the
`com_config` KV table are all ready, else `503`. Equivalently:

```bash
python -m pg_llm_batch health   # prints the report, exit 0 ready / 1 not ready
```

The Docker `HEALTHCHECK` and the compose `postgres` service both gate on the
same `pg_llm_batch_health_check()` SQL function.

---

## Embed as a git submodule

```bash
git submodule add https://github.com/ContextualWisdomLab/pg-llm-batch.git \
    third_party/pg-llm-batch
git submodule update --init --recursive
pip install -e third_party/pg-llm-batch
```

Then import the package directly:

```python
from pg_llm_batch import TokenCounter, PostgresBatchOrchestrator, BatchAPIClient
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from pg_llm_batch.batch_api_client import config_credentials_provider

dsn = my_app_dsn()               # your app already owns the DSN
config, secrets = PostgresConfigStore(dsn), SecretStore(dsn)
client = BatchAPIClient(dsn, config_credentials_provider(config, secrets))
```

Apply just the DDL subset into an existing database (idempotent, all tables are
2+ word `snake_case` and use `IF NOT EXISTS`):

```python
from pg_llm_batch import db
db.apply_schema(dsn)
```

The `credentials` argument to `BatchAPIClient` is a seam: pass
`config_credentials_provider(...)` to use the KV stores, or supply your own
`Callable[[str], GatewayCredentials]` to source credentials from your host app.

---

## Tests

```bash
pip install -e '.[test]'
pytest                       # unit tests (fakes, no DB needed)

docker compose up -d --build postgres
PG_LLM_BATCH_TEST_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm \
    pytest -m integration    # against the real pg_tiktoken + pg_cron container
```

## Docs

- [`docs/papers/`](docs/papers/) — CC BY 4.0 reference papers on LLM batching
  (PagedAttention/vLLM, DeepSpeed-FastGen) with citations.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
