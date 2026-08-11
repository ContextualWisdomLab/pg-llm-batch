# OpenTelemetry operation observability

## Purpose

`pg-llm-batch` can run standalone or as a module inside a larger service. The
ordinary `BatchAPIClient` therefore has no mandatory OpenTelemetry dependency.
A host that already owns an OpenTelemetry API/SDK can select
`OpenTelemetryBatchAPIClient` and receive one caller-operation span, one
operation-count measurement, and one duration measurement per outer public
batch-client operation.

OpenTelemetry Python currently supports Python 3.10 and newer, matching this
package's supported Python floor. Traces and metrics are stable signals in the
current OpenTelemetry Python implementation. The host remains responsible for
SDK providers, resource attributes, sampling, processors/readers, exporters,
collector endpoints, deployment identity, credentials, and retention.

## Installation and ownership boundary

The base package does not install or configure OpenTelemetry. A host may install
and configure it independently:

```bash
pip install 'opentelemetry-api>=1.44,<2' opentelemetry-sdk
```

Hosts can either call `OpenTelemetryBatchAPIClient.from_global_provider()` after
configuring process-global providers or inject compatible `tracer` and `meter`
objects directly. The explicit injection seam is preferred where a platform
owns observability centrally because it preserves standalone operation and
modular MSA composition without package-owned global state.

Telemetry is best-effort and never authoritative for provider behavior. Ordinary
telemetry exceptions and telemetry-originated `asyncio.CancelledError` during
instrument creation, span creation/mutation/closure, or metric recording are
contained. They cannot skip a provider call, replace its success result, mask
its failure, or swallow provider cancellation. Other process-level
`BaseException` control flow is not broadly swallowed.

## Signal contract

The bounded caller-operation vocabulary is:

- `upload_jsonl`
- `create_batch_job`
- `get_batch_status`
- `wait_for_batch`
- `download_results`
- `cancel_batch`

Each outer invocation uses the span name `pg_llm_batch.<operation>`. The metric
instruments are:

| Signal | Name | Unit | Bounded attributes |
| --- | --- | --- | --- |
| Span | `pg_llm_batch.<operation>` | n/a | operation name; `error.type` only on failure |
| Counter | `pg_llm_batch.client.operation.count` | `{operation}` | operation name, outcome, and failure-only `error.type` |
| Histogram | `pg_llm_batch.client.operation.duration` | `s` | operation name, outcome, and failure-only `error.type` |

Metric outcome is exactly `success` or `error`. The finite package-owned
`error.type` vocabulary is `CancelledError`, `ConfigError`, `ConnectionError`,
`Exception`, `GatewayError`, `OSError`, `PgLlmBatchError`, `RuntimeError`,
`TimeoutError`, `TokenLimitExceededError`, `TypeError`, `ValidationError`,
`ValueError`, and `_OTHER`.

The lookup uses exact Python class identity. Caller- or provider-defined classes,
including subclasses of documented classes, map to `_OTHER`; their dynamic class
names are not copied into telemetry. This keeps package-owned dimensions
predictable and low-cardinality as required by the OpenTelemetry `error.type`
contract.

## Failure span status

Automatic exception recording and automatic status-on-exception remain disabled
when the span is created. This is deliberate: the package does not hand provider
or caller exception messages, stack traces, exception objects, or traceback data
to a telemetry exporter.

For an operation that propagates a failure, the client now performs the narrower
standards-aligned sequence:

1. classify the failure into the finite package `error.type` vocabulary;
2. set that `error.type` on the span when a usable span exists;
3. lazily resolve the optional OpenTelemetry trace API and call
   `span.set_status(Status(StatusCode.ERROR))` **without a description**;
4. emit the error outcome metrics with the same bounded `error.type`;
5. close the span context with null exception arguments; and
6. re-raise the exact original exception object.

The OpenTelemetry tracing API says instrumentation libraries should normally
leave successful span status `Unset` and set `Error` when the operation is an
error. Current OpenTelemetry Python documentation uses
`Status(StatusCode.ERROR)` for manual instrumentation. The Recording Errors
semantic-conventions guidance also requires error classification to be
consistent across spans and metrics.

The current general Recording Errors guidance recommends using an exception
message as an Error status description when an exception causes failure. This
package intentionally does **not** copy that description because provider and
caller exception text can contain credentials, identifiers, prompts, provider
bodies, tenant data, or attacker-controlled high-cardinality values. The trace
API permits an Error status without a description; the package therefore keeps
the semantically meaningful Error code while applying its stricter documented
confidentiality boundary. This is an explicit privacy/security trade-off, not a
claim of complete OpenTelemetry automatic-instrumentation equivalence.

If the optional OpenTelemetry trace API is unavailable, `Status` construction
fails, or an injected span rejects `set_status`, the failure-status mutation is
best-effort and does not alter the application operation. Successful operations
remain status-`Unset`; the library never sets `Ok` merely to mark success.

## Privacy and cardinality contract

Package-owned telemetry does **not** record endpoint aliases, provider URLs,
batch/file/request/user/tenant identifiers, API keys, database connection
strings, request metadata, prompts/model inputs, response/result bodies,
exception messages, exception objects, stack traces, stack-frame locals, or
dynamic exception class names.

Do not add provider, tenant, URL, model, payload-derived, resource-ID, or other
unbounded values to these package instruments. Deployment identity belongs in
bounded host-owned OpenTelemetry resource attributes. Host SDK/exporter/backend
controls remain responsible for telemetry produced elsewhere in the process.

## Nested operation and concurrency boundary

`wait_for_batch()` and `download_results()` reuse `self.get_batch_status()` as an
internal step. These dynamic dispatches are not separate caller operations. A
context-local observation depth suppresses nested operation telemetry while
preserving independent concurrent caller operations. The depth is reset in a
`finally` block after success, failure, cancellation, or process-level control
flow.

Standard HTTP-client instrumentation remains independent. A host may instrument
aiohttp or an upstream gateway to observe individual requests while these
package metrics continue to represent caller-visible batch operations.

## Verification contract

The permanent tests prove:

- all six public operations emit the bounded success signal set;
- propagated failures retain the exact original exception object and finite
  `error.type` classification;
- `tests/test_opentelemetry_span_status.py` requires propagated failure spans to
  receive exactly one OpenTelemetry Error status object without an exception
  message or other sensitive status description;
- secret-like provider exception text and dynamic class names do not enter
  package-owned span/metric attributes or context-exit arguments;
- nested polling does not create duplicate caller-operation signals;
- telemetry provider and instrument failures do not alter provider behavior;
- provider cancellation is re-raised unchanged; and
- production statement, branch, and public-docstring gates remain 100% under
  repository policy, including Python 3.14 CI.

## References

OpenTelemetry Authors. (n.d.). *Error attributes*. OpenTelemetry semantic
conventions. Retrieved August 10, 2026, from
https://opentelemetry.io/docs/specs/semconv/registry/attributes/error/

OpenTelemetry Authors. (n.d.). *Recording errors*. OpenTelemetry semantic
conventions. Retrieved August 10, 2026, from
https://opentelemetry.io/docs/specs/semconv/general/recording-errors/

OpenTelemetry Authors. (n.d.). *Tracing API*. OpenTelemetry specification.
Retrieved August 10, 2026, from
https://opentelemetry.io/docs/specs/otel/trace/api/

OpenTelemetry Authors. (2026, July 22). *Instrumentation*. OpenTelemetry Python.
https://opentelemetry.io/docs/languages/python/instrumentation/

OpenTelemetry Authors. (2026, July 22). *Python*. OpenTelemetry.
https://opentelemetry.io/docs/languages/python/
