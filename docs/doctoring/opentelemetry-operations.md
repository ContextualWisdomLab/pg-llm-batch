# OpenTelemetry operation observability

## Purpose

`pg-llm-batch` can run by itself or as a module inside a larger service. The
ordinary `BatchAPIClient` therefore keeps OpenTelemetry optional. A host that
already owns an OpenTelemetry SDK can select `OpenTelemetryBatchAPIClient` and
receive one trace span, operation counter measurement, and duration histogram
measurement for each caller-invoked public batch-client operation.

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
Ordinary exceptions and telemetry-originated `asyncio.CancelledError` raised
while creating metric instruments or while starting, mutating, closing, or
recording telemetry do not prevent construction, skip the underlying provider
call, replace its return value, mask its exception, or swallow provider task
cancellation. An unavailable metric instrument is replaced locally by a no-op
instrument; this does not affect the ordinary uninstrumented client.

The isolation boundary is intentionally precise. Other `BaseException`
subclasses representing process-level control flow are not swallowed. This
preserves host shutdown, interrupt, and equivalent runtime-control semantics
instead of allowing an injected telemetry component to hide them.

## Signals

Every completed caller-invoked public operation emits the following custom
signals:

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

The outcome vocabulary is `success` or `error`. The complete custom
`error.type` vocabulary is:

- `CancelledError`
- `ConfigError`
- `ConnectionError`
- `Exception`
- `GatewayError`
- `OSError`
- `PgLlmBatchError`
- `RuntimeError`
- `TimeoutError`
- `TokenLimitExceededError`
- `TypeError`
- `ValidationError`
- `ValueError`
- `_OTHER`

The lookup uses **exact Python class identity**. A caller- or provider-defined
exception class, including a subclass of one of the documented classes, maps to
`_OTHER`; its class name is not copied into telemetry. This prevents attacker-
or tenant-controlled class names from becoming confidential or unbounded metric
dimensions. OpenTelemetry semantic conventions require `error.type` values to
be predictable and low-cardinality and define `_OTHER` as the fallback when no
more specific standardized identifier is available.

### Nested operation boundary

The public client API contains implementation reuse. `wait_for_batch()` polls
through `self.get_batch_status()`, and `download_results()` checks status through
the same dispatch path. Those calls are internal steps of the outer caller
operation; they are not additional caller invocations. The instrumented client
therefore emits only the outer `wait_for_batch` or `download_results` signal set
and suppresses nested `get_batch_status` operation telemetry.

Suppression uses a context-local observation depth rather than a shared mutable
instance flag. Each asynchronous task retains its own state, and the depth is
reset in a `finally` block after success, failure, cancellation, or process-level
control flow. Independent concurrent caller operations therefore remain
observable while internal dynamic dispatch stays hidden.

Standard HTTP client instrumentation remains independent. A host may still
observe every provider request and polling request through aiohttp or gateway
instrumentation without corrupting the library's caller-operation metrics.

## Privacy and cardinality contract

The instrumentation deliberately does **not** record:

- endpoint aliases or provider URLs;
- batch, file, request, user, or tenant identifiers;
- API keys, database connection strings, or other credentials;
- request metadata, prompts, model inputs, provider response bodies, or result
  records;
- exception objects, exception messages, stack traces, stack-frame local values,
  or caller-defined exception class names.

The library disables automatic exception recording and span-status mutation and
does not call `record_exception()`. A failure emits only the finite
`error.type` mapping above before the exact original exception is re-raised.
Span contexts are closed with null exception arguments, including during
`asyncio.CancelledError`, so injected context managers do not receive the
operation exception object or traceback. This stricter library boundary avoids
copying exception text, stack data, or dynamic type names into an export
pipeline because those values can contain provider bodies, identifiers,
credentials, prompts, tenant data, or attacker-controlled cardinality. Operators
must still apply appropriate SDK processor, exporter, and backend redaction
policies to telemetry created elsewhere in the host process.

Do not add dynamic provider, tenant, URL, resource-ID, model, payload-derived, or
runtime class-name attributes to these instruments. Such attributes can expose
confidential data and create unbounded metric cardinality. Add deployment
identity through the host SDK's bounded resource attributes instead.

## Failure and cancellation semantics

Telemetry is observational and does not alter the public operation result. A
successful operation returns the exact parent-client result. A failed operation
records its bounded error classification and re-raises the same exception
object. Provider task cancellation is classified as `CancelledError`, measured
once when instruments are available, closed without passing the cancellation
payload to the span context, and re-raised unchanged. Telemetry-originated
cancellation is isolated like an ordinary telemetry provider failure so it
cannot replace a provider result or provider cancellation. No provider request
is retried, swallowed, converted, or replayed by the observability layer.

The duration covers the complete caller-invoked public method call. For
`wait_for_batch`, this includes all polling and sleeps performed by that call.
For `download_results`, it includes the internal status check and bounded result
and error-file retrieval. These are end-to-end library-operation metrics, not a
replacement for standard HTTP client metrics. Hosts may independently
instrument aiohttp or an upstream gateway and correlate those child spans
through the active OpenTelemetry context.

## Verification contract

`tests/test_opentelemetry_operations.py` uses deterministic in-memory tracer and
meter doubles. It verifies every public operation, success and error paths,
metric names and units, optional dependency behavior, unchanged exception
propagation, and absence of a private endpoint alias from emitted telemetry.
`tests/test_opentelemetry_nested_operations.py` executes the real parent
`wait_for_batch()` and `download_results()` dispatch paths and proves that each
caller invocation emits only its outer signal set instead of an additional
`get_batch_status` signal set. `tests/test_opentelemetry_privacy_contract.py`
proves that a provider exception containing secret-like text is propagated to
the caller but is not copied into spans, context-exit arguments, or metric
attributes; it also constructs a secret-bearing exception class name and proves
that all signal types receive `_OTHER` rather than that untrusted name.
`tests/test_opentelemetry_lifecycle_safety.py` proves that provider cancellation
closes its span without exception payloads, telemetry-originated cancellation
cannot replace provider behavior, and metric-instrument construction failure
cannot disable the client. `tests/test_opentelemetry_control_flow.py` proves
that non-cancellation process-level control flow is propagated rather than
hidden. Production statement, branch, and public-docstring gates remain 100%.

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
