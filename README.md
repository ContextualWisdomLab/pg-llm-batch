# pg-llm-batch

Standalone **and** embeddable Postgres LLM batch engine. It counts tokens
**inside** PostgreSQL with [`pg_tiktoken`](https://github.com/postgresml/pg_tiktoken),
assembles OpenAI-compatible JSONL batches under token/byte/record limits, and
submits/polls/retrieves them through an authorized Batch API adapter.

Extracted from ContextualWisdomLab's `xtrmLLMBatchPython` batch core and
relicensed to **Apache-2.0** (see [`NOTICE`](NOTICE) for provenance).

## Why it exists

- **Token counting is authoritative.** Counts come from `pg_tiktoken` in the
  database, so the numbers used to pack a batch are exactly what the DB sees —
  there is no drifting Python-side tokenizer.
- **No secrets in the environment.** All configuration and credentials live in
  Postgres KV tables (`com_config`, `com_secrets`). The environment is only a
  *bootstrap transport* for the DSN and an optional Fernet key. This replaces
  the ~75 `os.getenv` reads in the upstream app. CLI secret values are entered
  through a no-echo prompt or bounded standard input, never as process arguments.
  Content-bearing `count-tokens` input is likewise accepted only through bounded
  UTF-8 standard input, so prompt text is not placed in process arguments.
- **Disk-free assembly.** JSONL payloads are stored as `JSONB` and reconstructed
  by JOIN, never written to disk.
- **Standalone or tenant-scoped lifecycle state.** `DurableBatchAPIClient`
  preserves the standalone contract, while `TenantDurableBatchAPIClient` binds
  shared-table lifecycle state to a trusted host-selected `tenant_scope` with
  forced PostgreSQL row-level security.

## Architecture

```
llm_requests ──▶ PostgresBatchOrchestrator.prepare_batches()
                     │  (TokenCounter → pg_tiktoken, BatchAccumulator)
                     ▼
   llm_batch_file_payloads (JSONB)  +  llm_batch_files  +  llm_jsonl_lines
                     │
                     ▼
        BatchAPIClient.upload_jsonl → create_batch_job → wait_for_batch → download_results
```

Provider-facing polling and retrieval stay behind the validated Python client
boundary. The former bundled `pg_cron` + `pgsql-http` provider retriever is
retired; automatic reconciliation remains a separate product capability rather
than a second database-side network authority. `BatchInferencePort` is
provider-neutral and does not discover providers/models, choose routing or
fallback, or resolve credentials. CWL production hosts bind those authorities
through released `contextual-orchestrator` contracts; mutable provider or model
selection is not owned by this repository.

| Piece | Module |
| --- | --- |
| Token counting + accumulation | `pg_llm_batch/token_counter.py` |
| Batch assembly + persistence | `pg_llm_batch/orchestrator.py` |
| Submit / poll / wait / retrieve | `pg_llm_batch/batch_api_client.py` |
| Durable standalone and tenant lifecycle clients | `pg_llm_batch/durable_client.py` |
| Tenant-qualified lifecycle persistence and reads | `pg_llm_batch/db.py` |
| Opt-in OpenTelemetry operations | `pg_llm_batch/observability.py` |
| KV config + encrypted secrets | `pg_llm_batch/config.py` |
| DDL subset | `pg_llm_batch/schema.sql` |
| Readiness (`/healthz`) | `pg_llm_batch/health.py` |
| CLI | `pg_llm_batch/cli.py` |

## Requirements

- PostgreSQL with `pg_tiktoken`. Fresh bundled database initialization does not
  create `pg_cron` or `http`; their image packages are retained temporarily only
  for existing-volume cleanup and rollback compatibility.
- Python 3.10+ with `psycopg[binary]` and `aiohttp` (installed via `pip install .`).
- Tenant-scoped lifecycle deployments require an application database role with
  `NOSUPERUSER NOBYPASSRLS` and a trusted host authorization boundary.

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
python -m pg_llm_batch config set-secret gateway_api_key.default # no-echo prompt
```

`config set-secret` never accepts the secret plaintext in process arguments.
On an interactive terminal it prompts without echo. Automation may pipe exactly
one bounded logical line on standard input from an existing credential source;
the command does not require or define a particular external secret manager.

Production gateway destinations must use HTTPS. Plain HTTP is accepted only for
explicit loopback development endpoints (`localhost`, `127.0.0.0/8`, or `::1`).
URLs containing user information, query parameters, fragments, whitespace, or
invalid ports are rejected before the API key is read from `com_secrets`.

Encrypt secrets at rest by exporting a Fernet key as bootstrap transport:

```bash
export PG_LLM_BATCH_SECRET_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
python -m pg_llm_batch config set-secret gateway_api_key.default # no-echo prompt
```

### 3. Count, submit, wait, retrieve

```bash
printf '%s' 'hello world' | python -m pg_llm_batch count-tokens --model gpt-4o --stdin
# {"model": "gpt-4o", "tokens": 2}

# after prepare_batches() has produced a memory://<file_id> payload:
python -m pg_llm_batch submit   --endpoint default --file-path memory://<file_id>
python -m pg_llm_batch poll     --endpoint default --batch-id <batch_id>
python -m pg_llm_batch wait     --endpoint default --batch-id <batch_id> \
    --poll-interval 5 --timeout 3600
python -m pg_llm_batch retrieve --endpoint default --batch-id <batch_id>
```

`count-tokens` requires the explicit `--stdin` source and accepts at most 1 MiB
of strict UTF-8 before configuration-store or PostgreSQL acquisition. The
command preserves the decoded text exactly, including trailing newlines because
they can affect the authoritative token count. Use `printf '%s'` when a shell
example should not append a newline. Prompt content is not accepted through an
argv option and rejected content is not copied into parser/runtime diagnostics.

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

## Durable lifecycle modes

Apply the canonical schema before using package-owned durable lifecycle state:

```python
from pg_llm_batch import db

db.apply_schema(dsn)
```

`DurableBatchAPIClient` keeps the original single-tenant facade and records under
the exact `standalone` scope. Shared-table hosts use
`TenantDurableBatchAPIClient` with a trusted tenant identity selected by the
host's authenticated authorization context:

```python
from pg_llm_batch import TenantDurableBatchAPIClient, get_tenant_remote_batch_state

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

The durable identity is `(tenant_scope, endpoint_alias, remote_batch_id)`.
Package helpers bind tenant scope with parameterized transaction-local PostgreSQL
context and the schema enables and forces default-deny RLS. Provider metadata,
resource identifiers, payloads, and headers never select `tenant_scope`.

Lifecycle-outbox RLS policy authority is catalog-verified rather than inferred
from the policy name. Canonical v2 binds the tenant comparison with
`OPERATOR(pg_catalog.=)` and resolves the transaction-local setting through
`pg_catalog.current_setting` in both `USING` and `WITH CHECK`. Migration 0008
accepts an existing v2 without policy DDL only when PostgreSQL reports the exact
all-command permissive `PUBLIC` role and canonical stored expressions. It
repairs same-name semantic drift, fails closed on unknown policy names, and
verifies the resulting policy before retiring v1/legacy names.

Migration 0008 also verifies canonical lifecycle timestamp CHECKs by catalog
semantics rather than constraint name alone. `valid_time` and `system_time`
canonical names are current only when `pg_constraint` reports a validated,
inheritable CHECK. A same-name wrong-kind, unvalidated, or `NO INHERIT`
constraint is rebuilt before the legacy timestamp check is removed; already
canonical constraints are left untouched on normal reapplication.

The custom PostgreSQL setting is **not** a tenant credential. A database role
that can execute arbitrary SQL can set arbitrary session state, so production
application roles must be `NOSUPERUSER NOBYPASSRLS`, must not be exposed through
a generic SQL surface, and still require normal authentication, authorization,
and SQL-injection controls. Direct SQL consumers that do not establish an
authorized tenant scope see no lifecycle rows after RLS is enabled.

See [`docs/remote-batch-lifecycle.md`](docs/remote-batch-lifecycle.md) for the
migration, rollback, pooling, recovery, custom-recorder, and assurance contract.

For a caller-owned logical archive, use `restore_postgres_logical_backup()` only
against an isolated libpq service after you can assert
`source_superusers_trusted=True`. The service name is not an authorization
boundary. Only `PGPASSWORD`, `PGPASSFILE`, and `PGSERVICEFILE` may be inherited.
The executor runs `pg_restore --single-transaction --exit-on-error`.
Custom-format restore seeks through the archive, so success is not required to
leave the descriptor at end-of-file. If metadata changes after `pg_restore`
exits zero, treat the target as unsafe and do not retry into the same service.
See [`docs/doctoring/postgres-logical-restore.md`](docs/doctoring/postgres-logical-restore.md)
for the operator steps.

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
In CWL production, that adapter must be driven by released contextual-orchestrator
authority rather than local provider/model discovery or paid fallback selection.

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
for transient `408`, `425`, `429`, `502`, `503`, and `504` responses and for
retryable aiohttp transport failures. TLS handshake and certificate failures are
never retried automatically; they fail after the first attempt because repeating
a request cannot repair peer identity or TLS policy. Certificate fingerprint
mismatches are never retried automatically for the same peer-identity reason.
A bounded RFC `Retry-After` delta or HTTP-date is honored. Delta-seconds accept
RFC ASCII digits only. Syntactically valid values above the configured maximum
are refused; malformed values use equal-jitter exponential fallback from 0.5
seconds up to 30 seconds. Upload, batch creation, and cancellation `POST`
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
    pytest -m integration    # against the real pg_tiktoken PostgreSQL container
```

## Docs

- [`docs/remote-batch-lifecycle.md`](docs/remote-batch-lifecycle.md)
  — standalone and tenant-scoped durable lifecycle operation, RLS trust boundary,
  migration, rollback, pooling, and recovery.
- [`docs/doctoring/tenant-scoped-lifecycle.md`](docs/doctoring/tenant-scoped-lifecycle.md)
  — tenant identity, RLS authority, compatibility, and APA 7 references.
- [`docs/doctoring/cli-secret-input.md`](docs/doctoring/cli-secret-input.md)
  — no-echo interactive secret entry, bounded stdin automation, fail-closed
  validation, verification, and security references.
- [`docs/doctoring/count-tokens-stdin-privacy.md`](docs/doctoring/count-tokens-stdin-privacy.md)
  — bounded UTF-8 prompt ingestion without argv exposure, exact text semantics,
  failure ordering, verification, and APA 7 references.
- [`docs/doctoring/legacy-pgsql-http-retrieval.md`](docs/doctoring/legacy-pgsql-http-retrieval.md)
  — retirement of direct SQL provider networking, existing-volume remediation,
  rollback, and the validated Python provider boundary.
- [`docs/doctoring/opentelemetry-operations.md`](docs/doctoring/opentelemetry-operations.md)
  — opt-in operation traces/metrics, host ownership, privacy and cardinality
  boundaries, verification, and APA 7 references.
- [`docs/papers/`](docs/papers/) — CC BY 4.0 reference papers on LLM batching
  (PagedAttention/vLLM, DeepSpeed-FastGen) with citations.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`].
