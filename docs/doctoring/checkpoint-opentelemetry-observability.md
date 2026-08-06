# Checkpoint OpenTelemetry observability doctoring

## Assurance statement

`OpenTelemetryCheckpointStore` emits bounded OpenTelemetry-compatible spans, completed-operation counts, and operation-duration histograms around durable checkpoint loads and saves. The package injects no SDK, exporter, global provider, or remote collector. It does not record tenant, consumer, batch, endpoint, file, digest, cursor, DSN, exception message, exception object, or checkpoint payload data.

The current OpenTelemetry semantic conventions 1.43.0 identify stable database-client attributes and error-recording rules. Semantic conventions for database client spans require `db.system.name` when the database system is known and define `postgresql` as its stable value. Recording errors requires a predictable low-cardinality `error.type` on failures and omission on success. The package therefore uses three fixed values only: `checkpoint_conflict`, `validation_error`, and `internal_error`.

Automatic span exception recording and status-on-exception are disabled. Checkpoint exceptions can retain structured consumer or batch details even when their public message is bounded, so package-owned observability records only the finite classification. Telemetry setup, mutation, and export failures are treated as observer failures and cannot replace the application result or exception.

## Operator boundary

The host owns OpenTelemetry provider, sampler, processor, exporter, resource, retention, access-control, and collector configuration. Operators should alert on bounded conflict/error ratios and duration distributions rather than adding remote resource identifiers as metric attributes. Caller-owned transaction methods describe the package call, not the eventual outer commit; database commit and downstream-effect observability remain host responsibilities.

## Verification

Deterministic tests prove exact delegation, caller-versus-package transaction labels, fixed span and metric attributes, seconds-based nonnegative durations, finite error classification, absence of protected identifiers, disabled exception recording, and preservation of the original result or exact exception during tracer, meter, span, exporter-surface, and clock failures. Production statement, branch, and public-docstring coverage remain at 100%.

## References (APA 7)

OpenTelemetry Authors. (n.d.). *OpenTelemetry semantic conventions 1.43.0*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/

OpenTelemetry Authors. (n.d.). *Semantic conventions for database client spans*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/database/database-spans/

OpenTelemetry Authors. (n.d.). *Recording errors*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/general/recording-errors/

OpenTelemetry Authors. (n.d.). *General error attributes*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/semconv/registry/attributes/error/

OpenTelemetry Authors. (n.d.). *Trace API*. OpenTelemetry. Retrieved August 7, 2026, from https://opentelemetry.io/docs/specs/otel/trace/api/

These references are recorded in APA 7 form. The quoted normative boundary is that `error.type SHOULD be predictable and SHOULD have low cardinality`; the implementation narrows that further to a package-owned three-value vocabulary.
