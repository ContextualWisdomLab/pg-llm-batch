# ADR 0008: Checkpoint OpenTelemetry observability

- Status: Accepted
- Date: 2026-08-07

## Context

The durable result-checkpoint store provides tenant isolation, exact compare-and-swap advancement, and caller-owned transaction methods. Operators nevertheless need standard latency, outcome, and conflict signals. Logging checkpoint identifiers or exception bodies would create a confidentiality and cardinality risk, while requiring an OpenTelemetry SDK or exporter would compromise standalone operation and could let observer failure alter commit or rollback behavior.

The wrapper may also decorate a compatible host-owned checkpoint store. A package-level checkpoint operation span therefore cannot truthfully assert a database technology or database-client semantic convention: the wrapped implementation may use PostgreSQL, another persistence technology, or no database at all.

## Decision

Add the opt-in `OpenTelemetryCheckpointStore` wrapper. It accepts a dependency-injected OpenTelemetry-compatible tracer and meter and delegates the four existing checkpoint operations without changing their arguments, return values, exception identity, transaction ownership, or storage semantics.

Package-owned spans and metrics never contain resource identifiers. In particular, tenant, consumer, batch, endpoint, file, digest, cursor, and DSN values are excluded. Span names, metric names, operation labels, transaction-owner labels, outcomes, and `error.type` values are fixed finite vocabularies. Automatic exception recording and automatic exception status are disabled because checkpoint exceptions can retain sensitive structured details.

The counter records completed operations. The histogram unit is seconds and records a nonnegative monotonic duration. Success omits `error.type`; failures use only `checkpoint_conflict`, `validation_error`, or `internal_error`. To follow the OpenTelemetry recording-errors contract without exposing exception text, failed checkpoint spans explicitly set OpenTelemetry status Error without a description, while successful checkpoint spans leave status Unset. The package resolves the host OpenTelemetry API's `StatusCode.ERROR` only when that optional API is available; missing or failing observer support never becomes an application dependency.

Package operation spans are storage-agnostic: they do not emit `db.system.name` or claim to be OpenTelemetry database-client spans. When a host needs PostgreSQL client telemetry, the host or database instrumentation layer owns the corresponding database semantic-convention attributes and spans.

Instrumentation is best effort. Tracer start, span entry, attribute mutation, explicit status mutation, span exit, metric creation, metric recording, optional status-code resolution, and clock failures are contained. The original checkpoint result or exact application exception remains authoritative. Exporter, processor, sampler, and provider ownership remains with the host. The package neither configures global OpenTelemetry state nor adds an SDK/exporter dependency.

## Consequences

Operators gain interoperable, low-cardinality checkpoint operation signals without exposing durable identities or provider-controlled data. Hosts may attach their own resource attributes outside the package boundary, but must not reinterpret package omission as authorization to add tenant or remote identifiers to high-cardinality telemetry.

Failed spans are discoverable through standard OpenTelemetry status in addition to the bounded `error.type`, without placing exception messages or status descriptions into package telemetry. Successful operations preserve the default Unset status rather than forcing `Ok`.

Storage-agnostic operation spans remain truthful when the wrapper decorates a compatible host-owned store. PostgreSQL-specific client instrumentation remains independently composable and can coexist with the package operation span without the package fabricating database semantics.

Telemetry cannot prove database commit, replication, or downstream business-effect durability beyond the wrapped method boundary. Caller-owned transaction methods measure the package call only; the caller remains responsible for the surrounding transaction outcome.

## Rollback

Remove the wrapper from host composition and continue using `PostgresBatchResultCheckpointStore` or the compatible host-owned store directly. No database migration, stored state, public checkpoint schema, dependency, or release version needs rollback. Removing instrumentation must not change durable checkpoint data or transaction behavior.
