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
        BatchAPIClient.upload_jsonl → create_batch_job → wait_for_batch → download_results
                     │
   (or) pg_cron job  cron_fetch_batch_results()  polls + imports results via pgsql-http
```

| Piece | Module |
| --- | --- |
| Token counting + accumulation | `pg_llm_batch/token_counter.py` |
| Batch assembly + persistence | `pg_llm_batch/orchestrator.py` |
| Submit / poll / wait / retrieve | `pg_llm_batch/batch_api_client.py` |
| Opt-in OpenTelemetry operations | `pg_llm_batch/observability.py` |
| KV config + encrypted secrets | `pg_llm_batch/config.py` |
| DDL subset | `pg_llm_batch/schema.sql` |
| Readiness (`/healthz`) | `pg_llm_batch/health.py` |
| CLI | `pg_llm_batch/cli.py` |

## Requirements

- PostgreSQL with `pg_tiktoken`, `pg_cron`, and `http` (pgsql-http). The bundled
  image (`docker/postgres/Dockerfile`) builds all three.
- Python 3.10+ with `psycopg[binary]` and `aiohttp` (installed via `pip install .`).

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

Production gateway destinations must use HTTPS. Plain HTTP is accepted only for
explicit loopback development endpoints (`localhost`, `127.0.0.0/8`, or `::1`).
URLs containing user information, query parameters, fragments, whitespace, or
invalid ports are rejected before the API key is read from `com_secrets`.

Encrypt secrets at rest by exporting a Fernet key as bootstrap transport:

```bash
export PG_LLM_BATCH_SECRET_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
python -m pg_llm_batch config set-secret gateway_api_key.default sk-your-key
```

### 3. Count, submit, wait, retrieve

```bash
python -m pg_llm_batch count-tokens --model gpt-4o --text "hello world"
# {"model": "gpt-4o", "tokens": 2}

# after prepare_batches() has produced a memory://<file_id> payload:
python -m pg_llm_batch submit   --endpoint default --file-path memory://<file_id>
python -m pg_llm_batch poll     --endpoint default --batch-id <batch_id>
python -m pg_llm_batch wait     --endpoint default --batch-id <batch_id> \
    --poll-interval 5 --timeout 3600
python -m pg_llm_batch retrieve --endpoint default --batch-id <batch_id>
```

`wait` returns when the remote status is `completed`, `failed`, `expired`, or
`cancelled`. It raises a structured gateway error when the configured timeout
expires, including the last observed remote status.

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
client = BatchAPIClient(
    dsn,
    config_credentials_provider(config, secrets),
    max_download_bytes=256 * 1024 * 1024,
)
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

Provider result and error files are streamed in 64 KiB chunks and limited to
128 MiB of decoded UTF-8 data by default. The limit is enforced after aiohttp
decompression and before JSONL parsing. Set `max_download_bytes` explicitly when
a reviewed deployment requires a larger bounded payload; oversized or invalid
UTF-8 responses fail with structured errors that do not echo provider content.

Idempotent provider `GET` operations use up to three total attempts by default
for transient `408`, `429`, `502`, `503`, and `504` responses and for aiohttp
transport failures. A bounded RFC `Retry-After` delta or HTTP-date is honored.
Delta-seconds accept RFC ASCII digits only. Syntactically valid values above the
configured maximum are refused; malformed values use equal-jitter exponential
fallback from 0.5 seconds up to 30 seconds. Upload, batch creation, and cancellation `POST`
operations are never retried automatically. Operators can override
`max_retry_attempts`, `retry_base_delay_seconds`, and
`retry_max_delay_seconds` in the `BatchAPIClient` constructor.

Hosts that already operate OpenTelemetry can select the opt-in subclass without
adding telemetry dependencies to ordinary standalone installations:

```python
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient

client = OpenTelemetryBatchAPIClient.from_global_provider(
    dsn,
    config_credentials_provider(config, secrets),
)
```

The emitted spans and metrics use bounded operation and outcome vocabularies and
never include endpoint aliases, provider URLs, resource IDs, credentials,
metadata, prompts, or provider response bodies. See the
[OpenTelemetry operation contract](docs/doctoring/opentelemetry-operations.md)
for signals, ownership boundaries, privacy rules, and APA 7 references.

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

- [`docs/doctoring/opentelemetry-operations.md`](docs/doctoring/opentelemetry-operations.md)
  — opt-in operation traces/metrics, host ownership, privacy and cardinality
  boundaries, verification, and APA 7 references.
- [`docs/papers/`](docs/papers/) — CC BY 4.0 reference papers on LLM batching
  (PagedAttention/vLLM, DeepSpeed-FastGen) with citations.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
