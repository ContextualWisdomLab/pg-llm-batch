# Checkpoint OpenTelemetry observability doctoring

## Assurance statement

`OpenTelemetryCheckpointStore` emits bounded OpenTelemetry-compatible spans, completed-operation counts, and operation-duration histograms around durable checkpoint loads and saves. The package injects no SDK, exporter, global provider, or remote collector. It does not record tenant, consumer, batch, endpoint, file, digest, cursor, DSN, exception message, exception object, or checkpoint payload data.

The current OpenTelemetry semantic conventions 1.44.0 distinguish generic application-operation telemetry from semantic conventions for database client spans. Database client spans require `db.system.name` when the database system is known, but the checkpoint wrapper is not itself a database-client instrumentation layer and may wrap a compatible host-owned store with another persistence implementation. The package therefore does **not** emit `db.system.name` on its checkpoint operation spans. Database-client semantic attributes remain owned by host or database instrumentation at the actual client boundary.

Recording errors requires a predictable low-cardinality `error.type` on failures and omission on success. The package narrows that vocabulary to three fixed values only: `checkpoint_conflict`, `validation_error`, and `internal_error`. The same OpenTelemetry recording-errors guidance says failed operations should use span status `Error` while successful operations leave status unset. Accordingly, failed checkpoint spans explicitly set OpenTelemetry status Error without a description, while successful checkpoint spans leave status Unset.

Automatic span exception recording and automatic status-on-exception remain disabled. Checkpoint exceptions can retain structured consumer or batch details even when their public message is bounded, so package-owned observability records only the finite classification and an explicit Error status with no description. The package resolves `opentelemetry.trace.StatusCode.ERROR` only when the host's optional OpenTelemetry API is importable. Missing status support, status mutation failures, telemetry setup, mutation, and export failures are observer failures and cannot replace the application result or exact exception.

## Operator boundary

The host owns OpenTelemetry provider, sampler, processor, exporter, resource, retention, access-control, collector configuration, and database-client instrumentation. Operators should alert on bounded conflict/error ratios, Error-status spans, and duration distributions rather than adding remote resource identifiers as metric attributes. Caller-owned transaction methods describe the package call, not the eventual outer commit; database commit and downstream-effect observability remain host responsibilities.

A PostgreSQL deployment may combine these storage-agnostic package spans with separately generated PostgreSQL client spans. The package span must not be reclassified as a database client span merely because the package-provided checkpoint store currently uses PostgreSQL; doing so would make the same public wrapper semantically false when a compatible non-PostgreSQL store is injected.

## Verification

Deterministic tests prove exact delegation, caller-versus-package transaction labels, fixed span and metric attributes, storage-agnostic operation spans, seconds-based nonnegative durations, finite error classification, explicit Error status on failed operations, Unset status on successful operations, absence of status descriptions and protected identifiers, disabled exception recording, optional-API fail-open observability behavior, and preservation of the original result or exact exception during tracer, meter, span, exporter-surface, status, and clock failures. Production statement, branch, and public-docstring coverage remain required at 100%.

## References (APA 7)

OpenTelemetry Authors. (n.d.). *OpenTelemetry semantic conventions 1.44.0*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/

OpenTelemetry Authors. (n.d.). *Semantic conventions for database client spans*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/db/database-spans/

OpenTelemetry Authors. (n.d.). *Recording errors*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/general/recording-errors/

OpenTelemetry Authors. (n.d.). *General error attributes*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/registry/attributes/error/

OpenTelemetry Authors. (n.d.). *Trace API*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/otel/trace/api/

These references are recorded in APA 7 form. The normative boundary used here is that failed operations should set span status `Error` and `error.type`, while successful spans leave status unset and omit `error.type`; the implementation additionally constrains `error.type` to a package-owned three-value vocabulary and omits status descriptions to avoid sensitive exception text.
