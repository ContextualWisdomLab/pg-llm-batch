# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Independent 1 MiB bounded-stream decoding for Files and Batches control-plane JSON before strict UTF-8 and object parsing.
- Opt-in OpenTelemetry spans, operation counts, and duration histograms for all
  caller-invoked public Batch API client operations, with explicit tracer/meter
  injection, lazy global-provider resolution, a finite documented `error.type`
  vocabulary with `_OTHER` fallback for caller-defined classes, a strict
  no-identifiers/no-payload/no-dynamic-class-name telemetry contract, fail-open
  isolation for ordinary telemetry failures and telemetry-originated
  cancellation, preservation of non-cancellation process-control exceptions,
  context-local suppression of internal status-poll telemetry, and local no-op
  metric fallbacks when instruments cannot be created.
- Bounded, streamed provider result and error downloads with a 128 MiB
  decoded-byte default, strict UTF-8 validation, body-free oversize errors,
  and fail-closed handling when a bounded byte stream is unavailable.
- Bounded retries for transient idempotent provider GET failures, including
  RFC Retry-After support and equal-jitter exponential fallback; side-effecting
  POST operations remain single-attempt.
- Durable remote batch lifecycle persistence through `DurableBatchAPIClient`
  and `llm_remote_batch_jobs`, with database-owned pre-request observation
  ordering, immutable terminal status identity, bounded curated metadata, and
  structured reservation/persistence recovery evidence.

### Fixed

- Made direct `serve-healthz` CLI invocation bind to loopback `127.0.0.1` by
  default, while the bundled container explicitly opts into `0.0.0.0` so broad
  listener exposure is a reviewable deployment decision rather than an implicit
  CLI default.
- Removed shell-expanded health-port configuration from the component image:
  both the readiness-server `CMD` and Docker `HEALTHCHECK` now use exec-form JSON
  at the fixed image default port `8080`, so environment text cannot become shell
  command syntax before Python listener validation. Custom ports require an
  explicit command and healthcheck override.
- Redacted public `/healthz` readiness output to omit database exceptions and
  other local diagnostic detail while preserving detailed operator diagnostics,
  fixed required-component readiness state, HTTP status semantics, and
  `Cache-Control: no-store`; unrecognized component names now remain on trusted
  local surfaces instead of silently widening the public probe schema. The HTTP
  handler also omits the default `Server header` so the stdlib identity and
  `Python version` are not disclosed by response metadata.
- Made public `/healthz` readiness validation non-coercive: malformed readiness
  shapes and non-boolean state fail closed to HTTP 503 instead of allowing truth
  coercion to create false-ready evidence.
- Made local readiness fail closed when `pg_llm_batch_health_check()` returns
  duplicate rows for a required component, while preserving those detailed rows
  for trusted operator diagnosis instead of allowing duplicate true rows to
  produce a successful CLI health result.
- Bounded the PostgreSQL readiness function with a parameterized transaction-local
  statement timeout so a connected but stalled health query cannot wait without
  a database-side execution limit.
- Served bounded concurrent readiness probes on independent daemon request
  threads with a 32-request admission ceiling; excess connections are closed
  before another worker/database check starts, and worker slots are returned on
  request completion or thread-start failure. This prevents one delayed check
  from serializing peers without permitting unbounded readiness resource use.
- Added a 5-second request-read timeout to each admitted `/healthz` connection
  so a slow or partial request cannot occupy one finite readiness worker slot
  indefinitely while the handler waits for the request line or headers.
- Enforced byte-accurate control-plane limits for multi-byte `memoryview`
  chunks using `nbytes`, and rejected malformed non-byte adapter chunks with
  bounded body-free diagnostics.
- Prevented caller- or provider-defined exception class names from entering
  OpenTelemetry span and metric attributes; unknown exact exception types now
  use the standardized low-cardinality `_OTHER` classification while the exact
  original exception object remains unchanged for the caller.
- Prevented `wait_for_batch()` and `download_results()` from inflating public
  `get_batch_status` telemetry with their internal dynamic-dispatch status
  checks while preserving independent concurrent caller observations.
- Rejected status-poll responses whose valid-looking provider batch identifier
  differs from the requested identifier before lifecycle recorder or PostgreSQL
  access; recovery metadata now retains only the trusted requested identifier.
- Redacted unsupported provider-generated batch identifiers from durable
  lifecycle recovery metadata and exception causes while retaining validated
  identifiers, observation order, operation, phase, endpoint alias, and bounded
  error type for reconciliation.
- Enforced NUL-free, 128-character endpoint aliases and 256-character remote
  batch, input, output, and error file string identifiers before order
  reservation, credential resolution, provider calls, custom lifecycle
  recorders, or PostgreSQL writes; unsafe optional text is normalized safely.
- Normalized provider metadata containing U+0000 in any object key or nested
  string to the deterministic empty object before injected lifecycle recorders
  or PostgreSQL `jsonb`, while preserving literal `\u0000` escape text.
- Prevented sparse newer remote lifecycle observations from reducing previously
  persisted request counters, and documented that lifecycle rows are mutable
  current-state projections while provider metadata is not a tenant
  authorization boundary.
- Synchronized the deployable PostgreSQL image initialization schema with the
  packaged canonical schema and added an exact-mirror regression gate, so
  container deployments cannot silently omit lifecycle or integrity migrations.
- Hardened provider `Retry-After` delta parsing to accept RFC ASCII digits only
  and refuse extremely long numeric guidance without leaking Python integer
  conversion errors.

### Changed

- Migrated package licensing to PEP 639 with an SPDX `Apache-2.0` expression,
  explicit `LICENSE` and `NOTICE` files, and a compatible setuptools backend
  floor so built artifacts expose normalized legal metadata without warnings.
- Consolidated immutable CI action, Python image, Rust toolchain image, and Ruff
  patch updates; setup-uv cache pruning is explicit to preserve the previous
  bounded cache-cost policy.

## [0.1.0] - 2026-07-12

### Added

- Initial standalone and embeddable PostgreSQL LLM batch engine extraction.