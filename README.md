# pg-llm-batch

Standalone **and** embeddable PostgreSQL LLM batch engine. It counts tokens
inside PostgreSQL with [`pg_tiktoken`](https://github.com/postgresml/pg_tiktoken),
assembles OpenAI-compatible JSONL batches under token, byte, and record limits,
and submits, polls, and retrieves them through an OpenAI-compatible Batch API.

The package was extracted from ContextualWisdomLab's `xtrmLLMBatchPython` batch
core and relicensed under Apache-2.0. See [`NOTICE`](NOTICE) for provenance.

## Why it exists

- **Authoritative token packing.** Counts come from `pg_tiktoken` in the same
  database that owns the batch state.
- **Disk-free payload assembly.** JSONL payloads are stored in PostgreSQL and
  reconstructed in memory rather than written to local disk.
- **Database-owned configuration.** Gateway configuration and encrypted secrets
  use `com_config` and `com_secrets`; environment variables are limited to
  bootstrap transport.
- **Durable provider reconciliation.** Opt-in lifecycle clients persist ordered
  remote state across restarts and worker failover.
- **Standalone or tenant-scoped operation.** Existing single-tenant consumers
  retain a compatible facade, while shared-table MSA deployments can use a
  trusted tenant-qualified identity and forced PostgreSQL row-level security.
- **Bounded provider resources.** Transport timeouts, retries, control-plane
  responses, output downloads, metadata, and diagnostic evidence use explicit
  limits and fail-closed validation.
- **Incremental large-result retrieval.** An opt-in async iterator bounds one
  physical JSONL line and one decoded record instead of retaining the complete
  provider file and parsed record list. A separate batch-wide physical-line
  ceiling counts blank lines across result and error files before parsing, and
  post-handoff transport failures never restart the file or replay records.
- **Embeddable seams.** Credential resolution, lifecycle recording, ordering,
  and telemetry can be supplied by `naruon`, `contextual-orchestrator`, or an
  independent host without making those services mandatory.

## Architecture

```text
llm_requests
    │
    ▼
PostgresBatchOrchestrator
    │  TokenCounter → pg_tiktoken
    │  BatchAccumulator → token/byte/record limits
    ▼
llm_batch_file_payloads + llm_batch_files + llm_jsonl_lines
    │
    ▼
BatchAPIClient
    ├─ upload_jsonl
    ├─ create_batch_job
    ├─ wait_for_batch
    └─ download_results

Optional bounded result iterator:
    StreamingBatchAPIClient
        ├─ open_batch_records → deterministic lifecycle owner
        └─ iter_batch_records → BatchResultRecord

Optional durable projection:
    DurableBatchAPIClient
        └─ tenant_scope="standalone"

    TenantDurableBatchAPIClient
        └─ (tenant_scope, endpoint_alias, remote_batch_id)
```

| Capability | Module |
| --- | --- |
| Token counting and accumulation | `pg_llm_batch/token_counter.py` |
| Batch assembly and persistence | `pg_llm_batch/orchestrator.py` |
| Provider submission, polling, and aggregate retrieval | `pg_llm_batch/batch_api_client.py` |
| Incremental bounded result and error records | `pg_llm_batch/result_streaming.py` |
| Durable standalone and tenant lifecycle clients | `pg_llm_batch/durable_client.py` |
| Tenant-qualified lifecycle persistence and reads | `pg_llm_batch/db.py` |
| Opt-in OpenTelemetry operations | `pg_llm_batch/observability.py` |
| KV configuration and encrypted secrets | `pg_llm_batch/config.py` |
| Canonical PostgreSQL DDL | `pg_llm_batch/schema.sql` |
| Readiness endpoint and SQL health function | `pg_llm_batch/health.py` |
| CLI | `pg_llm_batch/cli.py` |

## Requirements

- PostgreSQL with `pg_tiktoken`, `pg_cron`, and `http` (`pgsql-http`). The
  bundled PostgreSQL image builds all three.
- Python 3.10 or newer with package dependencies installed by `pip install .`.
- For tenant-scoped lifecycle state, an application role configured as
  `NOSUPERUSER NOBYPASSRLS` and a trusted host authorization boundary.

## Standalone quick start

### Start the stack

```bash
docker compose up -d --build
curl -fsS localhost:8080/healthz
```

### Initialize configuration

```bash
export PG_LLM_BATCH_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm
python -m pg_llm_batch init-db
python -m pg_llm_batch config set gateway base_url https://your-gateway/v1
python -m pg_llm_batch config set-secret \
  gateway_api_key.default sk-your-key
```

Production gateway destinations require HTTPS. Plain HTTP is accepted only for
explicit loopback development endpoints. URLs containing user information,
queries, fragments, whitespace, controls, backslashes, or invalid ports fail
before the API key is read.

Encrypt secrets at rest by providing a Fernet key as bootstrap transport:

```bash
export PG_LLM_BATCH_SECRET_KEY="$(
  python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
)"
```

### Count, submit, wait, and retrieve

```bash
python -m pg_llm_batch count-tokens --model gpt-4o --text "hello world"
python -m pg_llm_batch submit \
  --endpoint default \
  --file-path memory://<file_id>
python -m pg_llm_batch poll \
  --endpoint default \
  --batch-id <batch_id>
python -m pg_llm_batch wait \
  --endpoint default \
  --batch-id <batch_id> \
  --poll-interval 5 \
  --timeout 3600
python -m pg_llm_batch retrieve \
  --endpoint default \
  --batch-id <batch_id>
```

`wait` returns for `completed`, `failed`, `expired`, or `cancelled` and raises a
structured error when the bounded timeout expires.

Programmatic preparation:

```python
from pg_llm_batch import PostgresBatchOrchestrator

orchestrator = PostgresBatchOrchestrator(dsn)
prepared = orchestrator.prepare_batches(batch_uuid="<batch UUID>")
for payload in prepared["ready"]:
    print(payload.file_path, payload.request_count, payload.total_tokens)
```

## Durable lifecycle modes

Apply the canonical schema before using either durable client:

```python
from pg_llm_batch import db

db.apply_schema(dsn)
```

### Standalone durable state

`DurableBatchAPIClient` preserves the original recorder contract and stores
state under the exact `standalone` scope.

```python
from pg_llm_batch import DurableBatchAPIClient, get_remote_batch_state
from pg_llm_batch.batch_api_client import config_credentials_provider
from pg_llm_batch.config import PostgresConfigStore, SecretStore

credentials_provider = config_credentials_provider(
    PostgresConfigStore(dsn),
    SecretStore(dsn),
)

async with DurableBatchAPIClient(dsn, credentials_provider) as client:
    created = await client.create_batch_job(
        input_file_id="file-provider-id",
        endpoint_alias="default",
        endpoint="/v1/responses",
    )

state = get_remote_batch_state(dsn, "default", created["id"])
```

### Shared-table tenant state

`TenantDurableBatchAPIClient` requires a trusted tenant identity at construction.
The value must come from the host's authenticated authorization context.
Provider metadata and request content must never choose it.

```python
from pg_llm_batch import (
    TenantDurableBatchAPIClient,
    get_tenant_remote_batch_state,
)

async with TenantDurableBatchAPIClient(
    dsn,
    credentials_provider,
    tenant_scope="customer-42",
) as client:
    created = await client.create_batch_job(
        input_file_id="file-provider-id",
        endpoint_alias="default",
        endpoint="/v1/responses",
    )

state = get_tenant_remote_batch_state(
    dsn,
    "customer-42",
    "default",
    created["id"],
)
```

The durable identity is
`(tenant_scope, endpoint_alias, remote_batch_id)`. Package database helpers bind
scope with parameterized, transaction-local `set_config(..., true)`, and the
schema enables and forces default-deny row-level security.

The custom PostgreSQL setting is not a tenant credential. A database role that
can execute arbitrary SQL can set an arbitrary tenant scope. Do not expose the
application role through a generic SQL surface, and do not treat RLS as a
substitute for authentication, authorization, SQL-injection prevention, or
restricted database privileges. Production service identities must be
`NOSUPERUSER NOBYPASSRLS`.

Enabling RLS also changes direct SQL behavior: consumers that do not establish
an authorized transaction-local scope see no lifecycle rows. Migrate those
consumers to package helpers or a separately reviewed tenant-binding database
interface before deploying the schema.

See the complete [durable lifecycle operator contract](docs/remote-batch-lifecycle.md)
for migration, rollback, pooling, recovery, custom recorder, and assurance
boundaries.

## Embed as a module

```bash
git submodule add \
  https://github.com/ContextualWisdomLab/pg-llm-batch.git \
  third_party/pg-llm-batch
git submodule update --init --recursive
pip install -e third_party/pg-llm-batch
```

Use the public package directly:

```python
from pg_llm_batch import BatchAPIClient, PostgresBatchOrchestrator, TokenCounter

client = BatchAPIClient(
    dsn,
    credentials_provider,
    max_control_response_bytes=1 * 1024 * 1024,
    max_download_bytes=128 * 1024 * 1024,
)
```

The package remains independently operable. An embedding host can inject a
`Callable[[str], GatewayCredentials]`, lifecycle recorders, an observation
reserver, and OpenTelemetry providers without importing another CWL service.

## Resource and retry policy

### Control-plane JSON

Files and Batches metadata responses are streamed through an independent 1 MiB
decoded-byte budget before strict UTF-8 and JSON object parsing. The client does
not use whole-body `response.json()` or `response.text()` fallbacks. Custom
adapters without `content.iter_chunked` fail closed. Multi-byte `memoryview`
chunks are counted by `nbytes` rather than element count.

### Provider files

Output and provider error files are streamed in 64 KiB chunks and limited to
128 MiB of decoded UTF-8 data by default. The limit applies after HTTP
decompression and before JSONL parsing. Oversized and invalid UTF-8 responses
produce body-free structured diagnostics.

`download_results()` retains its aggregate compatibility contract and therefore
materializes each complete bounded file and parsed record list. For large or
shared workloads, use the opt-in context-managed iterator instead:

```python
from pg_llm_batch import StreamingBatchAPIClient

async with StreamingBatchAPIClient(
    dsn,
    credentials_provider,
    max_download_bytes=128 * 1024 * 1024,
    max_jsonl_line_bytes=1 * 1024 * 1024,
    max_jsonl_records=100_000,
    max_jsonl_physical_lines=100_000,
) as client:
    async with client.open_batch_records("batch-123", "default") as records:
        async for item in records:
            await persist_record(item.file_kind, item.record)
            if consumer_should_stop(item):
                break
```

The context-managed API explicitly closes the public iterator, its active nested
file iterator, and the response when the loop exits early. A bare `async for`
over `iter_batch_records()` must be exhausted or explicitly closed; Python does
not call `aclose()` merely because the loop uses `break`.

The iterator reads output records before provider error records, accepts CRLF
and final lines without a newline, skips blank lines, and requires every other
line to be strict UTF-8 containing one JSON object. The per-file total byte cap,
per-line byte cap, batch-wide physical line cap, and combined result-plus-error
record cap are enforced before excessive data is yielded. Result and error files
share the physical-line budget, and every blank line consumes it even though no
record is emitted. Empty, non-byte, and oversized adapter chunks fail closed, and
sanitized parser exceptions do not retain provider bytes or text in cause/context
links. Downstream persistence and backpressure remain host responsibilities;
collecting every yielded record recreates aggregate memory use. See
[`docs/result-streaming.md`](docs/result-streaming.md).

### Idempotent GET retries

Provider `GET` operations use up to three total attempts for `408`, `429`,
`502`, `503`, and `504` and for supported transport failures. Bounded RFC 9110
`Retry-After` delta-seconds or HTTP dates are honored. Malformed guidance uses
equal-jitter exponential fallback; valid guidance above the configured maximum
is refused. Retry eligibility ends before a response is handed to the body
consumer. A payload or response-close failure after handoff closes once and is
not retried, because restarting from byte zero could duplicate records already
delivered to the application. Side-effecting upload, creation, and cancellation
`POST` operations remain single-attempt.

## OpenTelemetry

Hosts that already operate OpenTelemetry can use the opt-in subclass without
adding telemetry dependencies to ordinary installations:

```python
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient

client = OpenTelemetryBatchAPIClient.from_global_provider(
    dsn,
    credentials_provider,
)
```

Signals use bounded operation, outcome, and error vocabularies and exclude
endpoint aliases, URLs, resource identifiers, credentials, metadata, prompts,
and provider bodies. See
[`docs/doctoring/opentelemetry-operations.md`](docs/doctoring/opentelemetry-operations.md).

## Health and readiness

`GET /healthz` returns `200` only when PostgreSQL, `pg_tiktoken`, and the
`com_config` table are ready; otherwise it returns `503`.

```bash
python -m pg_llm_batch health
```

The Docker health check and Compose PostgreSQL service use the same SQL health
function.

## Verification

```bash
pip install -e '.[test]'
pytest -m "not integration"

docker compose up -d --build postgres
PG_LLM_BATCH_TEST_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm \
  pytest -m integration
```

Protected CI verifies Python 3.10, 3.12, and 3.14; compilation; Ruff; 100%
production statement and branch coverage; 100% production docstrings; lockfile
freshness; source and wheel packaging; Compose validation; component and
PostgreSQL container builds; SAST; and security scanning.

## Documentation

- [`docs/remote-batch-lifecycle.md`](docs/remote-batch-lifecycle.md) — standalone
  and tenant lifecycle operations, RLS trust boundary, migration, rollback, and
  recovery.
- [`docs/result-streaming.md`](docs/result-streaming.md) — incremental result and
  error ordering, resource limits, compatibility, and host backpressure.
- [`docs/doctoring/tenant-scoped-lifecycle.md`](docs/doctoring/tenant-scoped-lifecycle.md)
  — authoritative security decision and APA 7 references.
- [`docs/doctoring/opentelemetry-operations.md`](docs/doctoring/opentelemetry-operations.md)
  — signal ownership, privacy, and cardinality.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — standalone and modular MSA boundaries.
- [`docs/papers/`](docs/papers/) — batching research references.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
