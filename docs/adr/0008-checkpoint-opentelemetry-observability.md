# ADR 0008: Checkpoint OpenTelemetry observability

- Status: Accepted
- Date: 2026-08-07

## Context

The durable result-checkpoint store provides tenant isolation, exact compare-and-swap advancement, and caller-owned transaction methods. Operators nevertheless need standard latency, outcome, and conflict signals. Logging checkpoint identifiers or exception bodies would create a confidentiality and cardinality risk, while requiring an OpenTelemetry SDK or exporter would compromise standalone operation and could let observer failure alter commit or rollback behavior.

## Decision

Add the opt-in `OpenTelemetryCheckpointStore` wrapper. It accepts a dependency-injected OpenTelemetry-compatible tracer and meter and delegates the four existing checkpoint operations without changing their arguments, return values, exception identity, transaction ownership, or database semantics.

Package-owned spans and metrics never contain resource identifiers. In particular, tenant, consumer, batch, endpoint, file, digest, cursor, and DSN values are excluded. Span names, metric names, operation labels, transaction-owner labels, outcomes, and `error.type` values are fixed finite vocabularies. Automatic exception recording and automatic exception status are disabled because checkpoint exceptions can retain sensitive structured details.

The counter records completed operations. The histogram unit is seconds and records a nonnegative monotonic duration. Success omits `error.type`; failures use only `checkpoint_conflict`, `validation_error`, or `internal_error`. The database technology attribute is the stable `db.system.name=postgresql` value.

Instrumentation is best effort. Tracer start, span entry, attribute mutation, span exit, metric creation, metric recording, and clock failures are contained. The original checkpoint result or exact application exception remains authoritative. Exporter, processor, sampler, and provider ownership remains with the host. The package neither configures global OpenTelemetry state nor adds an SDK/exporter dependency.

## Consequences

Operators gain interoperable, low-cardinality checkpoint operation signals without exposing durable identities or provider-controlled data. Hosts may attach their own resource attributes outside the package boundary, but must not reinterpret package omission as authorization to add tenant or remote identifiers to high-cardinality telemetry.

Telemetry cannot prove database commit, replication, or downstream business-effect durability beyond the wrapped method boundary. Caller-owned transaction methods measure the package call only; the caller remains responsible for the surrounding transaction outcome.

## Rollback

Remove the wrapper from host composition and continue using `PostgresBatchResultCheckpointStore` directly. No database migration, stored state, public checkpoint schema, dependency, or release version needs rollback. Removing instrumentation must not change durable checkpoint data or transaction behavior.
