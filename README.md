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
- **By default, provider credentials stay out of the environment in standalone mode.**
  Operational configuration and provider credentials live in Postgres KV tables
  (`com_config`, `com_secrets`). In standalone mode, the environment is only a
  *bootstrap transport* for the DSN and an optional Fernet key. The Fernet key is sensitive bootstrap secret material,
  not a provider credential, and must be protected accordingly. Embedded hosts
  may instead supply credentials through the documented
  `Callable[[str], GatewayCredentials]` integration boundary. This replaces the
  ~75 `os.getenv` reads in the upstream app.
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

### 2. Point it at your gateway (provider config + credential in the DB)

```bash
export PG_LLM_BATCH_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm
python -m pg_llm_batch init-db                                   # idempotent
python -m pg_llm_batch config set gateway base_url https://your-gateway/v1
```

Production gateway destinations must use HTTPS. Plain HTTP is accepted only for
explicit loopback development endpoints (`localhost`, `127.0.0.0/8`, or `::1`).
URLs containing user information, query parameters, fragments, whitespace, or
invalid ports are rejected before the API key is read from `com_secrets`.

For the protected-main-compatible credential path, install the optional Fernet
dependency, inject the Fernet key **before** constructing `SecretStore`, and use
a terminal prompt that fails closed if Python cannot disable echo. Do not place
the provider key in process argv, shell history, or command diagnostics:

```bash
pip install '.[secrets]'
export PG_LLM_BATCH_SECRET_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
python - <<'PY'
import getpass
import os
import warnings

from pg_llm_batch.bootstrap import resolve_secret_key
from pg_llm_batch.config import SecretStore

warnings.simplefilter("error", getpass.GetPassWarning)

store = SecretStore(
    os.environ["PG_LLM_BATCH_DSN"],
    fernet_key=resolve_secret_key(),
)
try:
    try:
        api_key = getpass.getpass("Gateway API key: ")
    except getpass.GetPassWarning as exc:
        raise SystemExit("Cannot disable terminal echo; refusing secret input") from exc
    store.set_secret("gateway_api_key.default", api_key)
finally:
    store.close()
PY
unset PG_LLM_BATCH_SECRET_KEY
```

This uses the existing database-backed `SecretStore.set_secret()` API and keeps
provider credential plaintext out of argv. Setting `PG_LLM_BATCH_SECRET_KEY`
before `SecretStore` construction ensures the example uses Fernet encryption
instead of the local/dev-only base64-obfuscation fallback; unsetting it after the
write shortens ambient key lifetime. The warning-to-error policy prevents
`getpass` from falling back to visibly echoed input when terminal echo control is
unavailable. ACTIVE-PR #85 adds an equivalent argv-safe `config set-secret` CLI
input path; until that PR is integrated, do not treat a plaintext positional CLI
secret example as a production procedure. Non-interactive host applications
should use their own secret-manager integration and the documented
`Callable[[str], GatewayCredentials]` boundary instead of weakening this prompt.

`PG_LLM_BATCH_SECRET_KEY` is sensitive bootstrap secret material. Keep it out of
shell history, logs, source control, images, and other ambient diagnostics; use a
secret-injection mechanism appropriate to the deployment. The generated-key
`export` above is a local bootstrap example, not a production secret-distribution
mechanism. Provider API credentials remain in `com_secrets` rather than
environment variables by default in standalone mode.

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
    max_control_response_bytes=1 * 1024 * 1024,
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

Files and Batches control-plane JSON responses are streamed through an
independent 1 MiB decoded-byte budget before strict UTF-8 and JSON object
parsing. The client never uses whole-body `response.json()` or
`response.text()` fallbacks, and adapters without `content.iter_chunked` fail
closed. Set `max_control_response_bytes` only for a reviewed provider metadata
contract; changing it does not alter the provider-file download budget.

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

Canonical product and acquisition-readiness documentation is indexed here so
buyers, contributors, and operators do not need chat history or PR-body
archaeology. The newly introduced canonical graph is **ACTIVE-PR #93** until it
reaches protected `main`; ACTIVE-PR or PARTIAL material is not shipped behavior.
Use [Documentation fitness and maturity](docs/DOCUMENTATION_FITNESS.md) as the
status authority for each documentation family and capability.

- [Architecture](ARCHITECTURE.md), [PRD](docs/product/PRD.md), [TRD](docs/product/TRD.md), and [public API/compatibility contract](docs/product/API_CONTRACT.md)
- [UML behavior views](docs/architecture/UML.md) and [ERD/data model](docs/architecture/ERD.md)
- [Security policy](SECURITY.md), [threat model](docs/THREAT_MODEL.md), [data governance/privacy](docs/DATA_GOVERNANCE.md), [test strategy](docs/TEST_STRATEGY.md), and [operability/recovery](docs/OPERABILITY.md)
- [Release acceptance](docs/RELEASE_ACCEPTANCE.md), [traceability](docs/TRACEABILITY.md), and [ADR index](docs/adr/README.md)
- [Documentation fitness and maturity matrix](docs/DOCUMENTATION_FITNESS.md)

Additional method and research documentation:

- [`docs/doctoring/opentelemetry-operations.md`](docs/doctoring/opentelemetry-operations.md)
  — opt-in operation traces/metrics, host ownership, privacy and cardinality
  boundaries, verification, and APA 7 references.
- [`docs/papers/`](docs/papers/) — CC BY 4.0 reference papers on LLM batching
  (PagedAttention/vLLM, DeepSpeed-FastGen) with citations.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
