# OpenTelemetry operation observability

## Purpose

`pg-llm-batch` can run by itself or as a module inside a larger service. The
ordinary `BatchAPIClient` therefore keeps OpenTelemetry optional. A host that
already owns an OpenTelemetry SDK can select `OpenTelemetryBatchAPIClient` and
receive one trace span, operation counter measurement, and duration histogram
measurement for each public batch-client operation.

OpenTelemetry Python supports Python 3.10 and newer, and its trace and metric
signals are stable. This matches the package's supported Python floor without
forcing an exporter, collector, or vendor choice on standalone users.

## Installation and ownership boundary

The base package does not install OpenTelemetry. Install the API and whichever
SDK/exporter the host service has selected:

```bash
pip install 'opentelemetry-api>=1.44,<2' opentelemetry-sdk
```

The host application remains responsible for SDK resource attributes, sampling,
span processors, metric readers, exporters, collector endpoints, credentials,
and retention. The library only creates spans and synchronous metric
instruments through supplied API objects.

### Process-global provider

```python
from pg_llm_batch.batch_api_client import config_credentials_provider
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient

config = PostgresConfigStore(dsn)
secrets = SecretStore(dsn)
client = OpenTelemetryBatchAPIClient.from_global_provider(
    dsn,
    config_credentials_provider(config, secrets),
)
```

`from_global_provider()` imports `opentelemetry.trace` and
`opentelemetry.metrics` only when called. Missing optional support produces an
actionable `RuntimeError`; importing or using `BatchAPIClient` remains
unaffected.

### Explicit dependency injection

Services that avoid process-global providers can inject any compatible tracer
and meter:

```python
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient

client = OpenTelemetryBatchAPIClient(
    dsn,
    credentials_provider,
    tracer=service_tracer,
    meter=service_meter,
)
```

This seam preserves standalone operation and allows a CWL service mesh or other
MSA host to apply its own resource, tenant, exporter, and sampling policies.

## Signals

Every completed public operation emits the following custom signals:

| Signal | Name | Unit | Stable attributes |
| --- | --- | --- | --- |
| Span | `pg_llm_batch.<operation>` | Not applicable | `pg_llm_batch.operation.name`; `error.type` only on failure |
| Counter | `pg_llm_batch.client.operation.count` | `{operation}` | operation name, outcome, and `error.type` only on failure |
| Histogram | `pg_llm_batch.client.operation.duration` | `s` | operation name, outcome, and `error.type` only on failure |

The bounded operation-name vocabulary is:

- `upload_jsonl`
- `create_batch_job`
- `get_batch_status`
- `wait_for_batch`
- `download_results`
- `cancel_batch`

The outcome vocabulary is `success` or `error`. `error.type` is the canonical
Python exception class name, such as `GatewayError` or `ValidationError`.
OpenTelemetry recommends predictable, low-cardinality `error.type` values and
recommends including error classification on operation duration metrics.

## Privacy and cardinality contract

The instrumentation deliberately does **not** record:

- endpoint aliases or provider URLs;
- batch, file, request, user, or tenant identifiers;
- API keys, database connection strings, or other credentials;
- request metadata, prompts, model inputs, provider response bodies, or result
  records;
- exception messages or stack-frame local values.

Exception events are delegated to the configured tracer. Operators must still
apply their SDK's processor, exporter, and backend redaction policies. The
library disables automatic exception recording and span-status mutation before
recording the original exception exactly once, preventing duplicate exception
events from the context manager.

Do not add dynamic provider, tenant, URL, resource-ID, model, or payload-derived
attributes to these instruments. Such attributes can expose confidential data
and create unbounded metric cardinality. Add deployment identity through the
host SDK's bounded resource attributes instead.

## Failure semantics

Telemetry is observational and does not alter the public operation result. A
successful operation returns the exact parent-client result. A failed operation
records its bounded error classification and re-raises the same exception
object. No provider request is retried, swallowed, converted, or replayed by the
observability layer.

The duration covers the complete public method call. For `wait_for_batch`, this
includes all polling and sleeps performed by that call. This is an end-to-end
library-operation metric, not a replacement for standard HTTP client metrics.
Hosts may independently instrument aiohttp or an upstream gateway and correlate
those child spans through the active OpenTelemetry context.

## Verification contract

`tests/test_opentelemetry_operations.py` uses deterministic in-memory tracer and
meter doubles. It verifies every public operation, success and error paths,
metric names and units, optional dependency behavior, unchanged exception
propagation, and absence of a private endpoint alias from emitted telemetry.
Production statement, branch, and public-docstring gates remain 100%.

## References

OpenTelemetry Authors. (n.d.). *Error attributes*. OpenTelemetry semantic
conventions. Retrieved August 5, 2026, from
https://opentelemetry.io/docs/specs/semconv/registry/attributes/error/

OpenTelemetry Authors. (n.d.). *Recording errors*. OpenTelemetry semantic
conventions. Retrieved August 5, 2026, from
https://opentelemetry.io/docs/specs/semconv/general/recording-errors/

OpenTelemetry Authors. (2026, July 22). *Python*. OpenTelemetry.
https://opentelemetry.io/docs/languages/python/

OpenTelemetry Authors. (2026, July 16). *opentelemetry-api 1.44.0* [Computer
software]. Python Package Index.
https://pypi.org/project/opentelemetry-api/1.44.0/
