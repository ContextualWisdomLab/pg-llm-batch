# pg-llm-batch

Standalone **and** embeddable PostgreSQL-backed LLM batch engine. It counts tokens inside PostgreSQL with [`pg_tiktoken`](https://github.com/postgresml/pg_tiktoken), assembles JSONL batches under explicit token/byte/record limits, and owns durable standalone or tenant-scoped lifecycle state behind a provider-neutral batch boundary.

Extracted from ContextualWisdomLab's `xtrmLLMBatchPython` batch core and relicensed to **Apache-2.0**; see [`NOTICE`](NOTICE) for provenance.

> **Commercial dependency status:** on this Draft stack, the default runtime manifest pins `pg8000==1.31.5`; Psycopg is retained only in optional test/development dependencies for legacy-adapter parity. That is materially different from protected `main`, but it is not released commercial authority. [Issue #322](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/322) remains open until the driver change is normally integrated and the exact protected release head has clean package/license/vulnerability/SBOM/provenance/reproducibility evidence. A green Draft does not make the dependency transition shipped.
>
> Package-created remote PostgreSQL transport also has a separate open security boundary: this Draft does not yet prove mandatory encryption plus authenticated server identity. [Issue #123](https://github.com/ContextualWisdomLab/pg-llm-batch/issues/123) owns that contract. The loopback development examples below are not evidence for secure remote PostgreSQL deployment.

## Why it exists

- **Database-authoritative token accounting.** Token counts come from `pg_tiktoken`, so packing decisions use the same database-visible count that is persisted with batch state.
- **Durable asynchronous lifecycle.** Standalone and tenant-scoped clients persist remote batch identity, status, observation order, checkpoints, and reconciliation evidence in PostgreSQL instead of keeping lifecycle truth in one process.
- **Provider-neutral infrastructure seam.** PostgreSQL client construction is behind `PostgresDriverPort`; provider-facing batch work remains behind the package's validated batch client boundary rather than database-side provider networking.
- **Explicit size limits.** JSONL assembly, control responses, provider result files, configuration input, and diagnostic surfaces use finite limits rather than unbounded materialization.
- **Tenant isolation.** Shared lifecycle state binds trusted host-selected `tenant_scope` into transaction-local PostgreSQL context and forces default-deny RLS on the tenant lifecycle relation.
- **Content-conscious diagnostics.** Credential, prompt, provider payload, and rejected-value content is kept out of ordinary process arguments, package diagnostics, and optional telemetry where the owning contract requires it.

## Architecture

```text
llm_requests ──▶ PostgresBatchOrchestrator.prepare_batches()
                     │  (TokenCounter → pg_tiktoken, BatchAccumulator)
                     ▼
   llm_batch_file_payloads (JSONB) + llm_batch_files + llm_jsonl_lines
                     │
                     ▼
       BatchAPIClient / BatchInferencePort-compatible provider boundary
                     │
                     ▼
       durable lifecycle + tenant/RLS + reconciliation evidence
```

Provider-facing polling and retrieval stay outside PostgreSQL. The former bundled `pg_cron` + `pgsql-http` provider retriever is retired; automatic reconciliation is a separate product capability rather than a second database-side network authority.

| Piece | Module |
| --- | --- |
| Token counting + accumulation | `pg_llm_batch/token_counter.py` |
| Batch assembly + persistence | `pg_llm_batch/orchestrator.py` |
| Submit / poll / wait / retrieve | `pg_llm_batch/batch_api_client.py` |
| Durable standalone and tenant lifecycle clients | `pg_llm_batch/durable_client.py` |
| Tenant-qualified lifecycle persistence and reads | `pg_llm_batch/db.py` |
| PostgreSQL driver abstraction | `pg_llm_batch/postgres_driver_port.py` |
| Admitted runtime driver selection | `pg_llm_batch/postgres_driver_runtime.py` |
| KV config + encrypted-secret store | `pg_llm_batch/config.py` |
| Optional OpenTelemetry operations | `pg_llm_batch/observability.py` |
| DDL subset | `pg_llm_batch/schema.sql` |
| Readiness (`/healthz`) | `pg_llm_batch/health.py` |
| CLI | `pg_llm_batch/cli.py` |

## Requirements

- PostgreSQL with `pg_tiktoken`. Fresh bundled database initialization does not create `pg_cron` or `http`; their image packages are retained temporarily for existing-volume cleanup and rollback compatibility.
- Python 3.10+.
- On this Draft stack, the default Python runtime installs exact `pg8000==1.31.5` plus `aiohttp`; Psycopg is optional test/development-only legacy-adapter evidence.
- Tenant-scoped lifecycle deployments require an application role with `NOSUPERUSER NOBYPASSRLS` and a trusted host authorization boundary.
- The retained pg8000 runtime accepts only its reviewed single-host URI/keyword subset. Unsupported libpq semantics fail closed rather than being approximated.
- Remote production PostgreSQL must not be treated as transport-secure from this Draft alone; issue #123 remains the owner for mandatory TLS/server-identity policy.

---

## Standalone development and verification

The bundled Compose profile keeps PostgreSQL host publication on loopback and supplies the component password through a mounted Compose secret. `compose_bootstrap` combines the credential-free target and mounted password only in process memory through the selected PostgreSQL driver.

For a new disposable Compose project, generate one development password and retain it for the life of that `pgdata` volume:

```bash
export PG_LLM_BATCH_POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Save this value outside the repository in your local secret manager.
docker compose up -d --build
curl -fsS localhost:8080/healthz
```

PostgreSQL uses the initialization password only when the data directory is first created. Reusing the same volume therefore requires the same database-role credential unless you deliberately rotate that role inside PostgreSQL. If a disposable development password is intentionally lost, `docker compose down -v` deletes the local database volume; the next start initializes a new database.

### Host-side CLI during local development

The retained production pg8000 adapter does **not** inherit libpq `PGPASSFILE` semantics. Do not copy the old Psycopg quick-start pattern that paired a credential-free DSN with `PGPASSFILE` and assume pg8000 will consume it.

For the loopback-only development profile, one currently supported host path is to construct the password-bearing `PG_LLM_BATCH_DSN` in the environment rather than in argv, then unset both bootstrap variables when the session ends. This is a development mechanism, not the secure-remote production contract:

```bash
export PG_LLM_BATCH_DSN="$(python - <<'PY'
import os
from urllib.parse import quote
password = quote(os.environ['PG_LLM_BATCH_POSTGRES_PASSWORD'], safe='')
print(f'postgresql://pgllm:{password}@127.0.0.1:5432/pgllm')
PY
)"
unset PG_LLM_BATCH_POSTGRES_PASSWORD

python -m pg_llm_batch init-db
python -m pg_llm_batch health

unset PG_LLM_BATCH_DSN
```

Explicit CLI `--dsn` values have a different confidentiality boundary: password, `passfile`, TLS private-key, TLS key-password, and OAuth-client-secret material is rejected before connection work so credentials are not normalized into an argv transport. See [`docs/doctoring/bootstrap-dsn-precedence.md`](docs/doctoring/bootstrap-dsn-precedence.md).

### Configure the provider boundary

```bash
python -m pg_llm_batch config set gateway base_url https://your-gateway/v1
python -m pg_llm_batch config set-secret gateway_api_key.default
```

`config set-secret` does not accept secret plaintext in process arguments. Interactive entry is no-echo; automation may provide one bounded logical line on standard input from an already-owned credential source.

Production gateway destinations require HTTPS. Plain HTTP is accepted only for explicit loopback development endpoints (`localhost`, `127.0.0.0/8`, or `::1`). User information, query parameters, fragments, whitespace, and invalid ports are rejected before provider credentials are acquired.

To encrypt package-managed secrets at rest, supply a Fernet bootstrap key through the reviewed deployment path, for example in a local development shell:

```bash
export PG_LLM_BATCH_SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
python -m pg_llm_batch config set-secret gateway_api_key.default
```

### Count, submit, wait, retrieve

```bash
printf '%s' 'hello world' | python -m pg_llm_batch count-tokens --model gpt-4o --stdin

# after prepare_batches() has produced a memory://<file_id> payload:
python -m pg_llm_batch submit   --endpoint default --file-path memory://<file_id>
python -m pg_llm_batch poll     --endpoint default --batch-id <batch_id>
python -m pg_llm_batch wait     --endpoint default --batch-id <batch_id> --poll-interval 5 --timeout 3600
python -m pg_llm_batch retrieve --endpoint default --batch-id <batch_id>
```

`count-tokens` accepts strict UTF-8 only through the explicit stdin source and enforces its bounded input contract before configuration-store or PostgreSQL acquisition. Prompt text is not accepted through an argv option and rejected content is not reflected into parser/runtime diagnostics.

Programmatic preparation remains available:

```python
import os
from pg_llm_batch import PostgresBatchOrchestrator

orchestrator = PostgresBatchOrchestrator(os.environ["PG_LLM_BATCH_DSN"])
result = orchestrator.prepare_batches(batch_uuid="<uuid or input_file_path>")
for payload in result["ready"]:
    print(payload.file_path, payload.request_count, payload.total_tokens)
```

## Health / readiness

`GET /healthz` returns `200` only when the package's database-side readiness contract is satisfied; otherwise it returns `503`.

```bash
python -m pg_llm_batch health
```

The Docker `HEALTHCHECK` and Compose PostgreSQL service use the package-owned health function rather than treating mere TCP acceptance as product readiness.

---

## Durable lifecycle modes

Apply the canonical schema before using package-owned durable lifecycle state:

```python
from pg_llm_batch import db

db.apply_schema(dsn)
```

`DurableBatchAPIClient` retains the standalone facade and records under the exact `standalone` scope. Shared-table hosts use `TenantDurableBatchAPIClient` with tenant identity selected by the host's authenticated authorization context:

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

The durable identity is `(tenant_scope, endpoint_alias, remote_batch_id)`. Package helpers validate tenant scope before the owned lifecycle path, bind it with parameterized transaction-local PostgreSQL context, and rely on forced RLS for the tenant lifecycle relation. Provider metadata, resource identifiers, payloads, and headers never select tenant identity.

The PostgreSQL custom setting is not a tenant credential. Roles that can execute arbitrary SQL can set arbitrary session state, so production still requires normal authentication, authorization, SQL-injection controls, and an application role that cannot bypass RLS.

See [`docs/remote-batch-lifecycle.md`](docs/remote-batch-lifecycle.md) for migration, rollback, pooling, recovery, custom-recorder, and assurance boundaries.

## Recovery boundary

The repository contains bounded backup, restore, catalog, replay, and recovery-evidence primitives. Each primitive proves only its documented slice; none by itself establishes end-to-end PITR, RPO/RTO, HA/DR, CSAP, SOC 2, or a deployment certification.

For a caller-owned logical archive, `restore_postgres_logical_backup()` uses an isolated libpq-service execution boundary for `pg_restore`. That subprocess contract is distinct from package-created pg8000 connections and retains its own restricted libpq environment. See [`docs/doctoring/postgres-logical-restore.md`](docs/doctoring/postgres-logical-restore.md).

## Embedding boundary

The codebase supports submodule-style embedding mechanically. On this Draft stack the default Python runtime has moved to exact pg8000 and Psycopg is optional test/development-only, but that transition is not protected/released authority until #322 integrates normally and immutable release evidence is complete.

```bash
git submodule add https://github.com/ContextualWisdomLab/pg-llm-batch.git third_party/pg-llm-batch
git submodule update --init --recursive
pip install -e third_party/pg-llm-batch
```

Then import the package directly:

```python
from pg_llm_batch import TokenCounter, PostgresBatchOrchestrator, BatchAPIClient
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from pg_llm_batch.batch_api_client import config_credentials_provider

config = PostgresConfigStore(dsn)
secrets = SecretStore(dsn)
client = BatchAPIClient(
    dsn,
    config_credentials_provider(config, secrets),
    max_download_bytes=256 * 1024 * 1024,
    max_control_response_bytes=1 * 1024 * 1024,
)
```

The credentials provider is an anti-corruption seam: callers may use the package's PostgreSQL-backed configuration/secret store or provide a host-owned `Callable[[str], GatewayCredentials]`.

## Provider I/O limits and retry semantics

Files/Batches control-plane JSON uses an independent decoded-byte budget before strict UTF-8 and JSON-object parsing. Provider result/error files are streamed in bounded chunks and checked against `max_download_bytes` before JSONL parsing. Adapters that cannot provide the required bounded stream contract fail closed.

Idempotent provider `GET` operations may retry reviewed transient HTTP/transport failures within bounded attempts and backoff. Upload, batch creation, and cancellation `POST` operations are not retried automatically. TLS handshake/certificate and peer-identity failures are not treated as ordinary transient retries.

## Observability

Hosts that already operate OpenTelemetry may opt into `OpenTelemetryBatchAPIClient`. Emitted spans and metrics use bounded operation/outcome vocabularies and exclude endpoint aliases, provider URLs, resource identifiers, credentials, metadata, prompts, and provider bodies. See [`docs/doctoring/opentelemetry-operations.md`](docs/doctoring/opentelemetry-operations.md).

## Tests

The default runtime graph on this Draft uses pg8000. The `test`/`dev` dependency sets intentionally retain exact Psycopg only to verify legacy adapter compatibility during the migration; that optional evidence must not be confused with the production dependency graph.

```bash
pip install -e '.[test]'
pytest

export PG_LLM_BATCH_POSTGRES_PASSWORD="<same locally retained development password>"
docker compose up -d --build postgres
# Supply PG_LLM_BATCH_TEST_DSN through the test harness's reviewed local credential path.
pytest -m integration
```

Repository CI additionally verifies supported Python versions, exact owned production statement/branch coverage, public docstrings, lock/package integrity, and PostgreSQL/container runtime smokes. Release Acceptance is necessary but does not substitute for protected integration, independent review, security controls, SBOM/provenance, or the immutable release boundary.

## Docs

- [`docs/remote-batch-lifecycle.md`](docs/remote-batch-lifecycle.md) — durable lifecycle, tenant identity, RLS, migration, rollback, pooling, and recovery.
- [`docs/doctoring/tenant-scoped-lifecycle.md`](docs/doctoring/tenant-scoped-lifecycle.md) — tenant/RLS authority and references.
- [`docs/doctoring/bootstrap-dsn-precedence.md`](docs/doctoring/bootstrap-dsn-precedence.md) — bootstrap source precedence, argv confidentiality, and concrete-driver boundary.
- [`docs/doctoring/cli-secret-input.md`](docs/doctoring/cli-secret-input.md) — no-echo and bounded stdin secret input.
- [`docs/doctoring/count-tokens-stdin-privacy.md`](docs/doctoring/count-tokens-stdin-privacy.md) — bounded UTF-8 prompt ingestion without argv exposure.
- [`docs/doctoring/legacy-pgsql-http-retrieval.md`](docs/doctoring/legacy-pgsql-http-retrieval.md) — retirement of direct SQL provider networking.
- [`docs/doctoring/opentelemetry-operations.md`](docs/doctoring/opentelemetry-operations.md) — telemetry ownership, privacy, cardinality, verification, and references.
- [`docs/papers/`](docs/papers/) — reference papers used by repository doctoring.

## License and release authority

The pg-llm-batch repository's original source is Apache-2.0; see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Third-party dependencies retain their own licenses.

On this Draft stack, the default runtime manifest pins `pg8000==1.31.5`; Psycopg is optional test/development-only legacy-adapter evidence. Issue #322 remains open because commercial acceptance is not a branch-local dependency declaration: the change must reach protected main through normal governance and the immutable release must re-prove the final package, dependency-license inventory, vulnerability state, SBOM, provenance, reproducibility, and rollback evidence.

Issue #123 independently remains open for package-created remote PostgreSQL transport encryption and authenticated server identity. Do not present a green #323/#321 Draft as completion of either protected release or secure-remote transport policy.
