# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Optional OpenTelemetry-compatible checkpoint spans and metrics through
  `OpenTelemetryCheckpointStore`, with dependency-injected tracer and meter,
  fixed low-cardinality operation and transaction-owner labels, a seconds-based
  monotonic duration histogram, and the finite failure vocabulary
  `checkpoint_conflict, validation_error, and internal_error`. Package-owned
  signals omit tenant, consumer, batch, endpoint, file, digest, cursor, DSN,
  exception-message, and provider-payload data; automatic exception recording
  and automatic status-on-exception are disabled. Failed checkpoint spans set
  the host OpenTelemetry API's `StatusCode.ERROR` without a description when
  available, while successful checkpoint spans leave status Unset. Optional
  status resolution, explicit status mutation, ordinary telemetry, and clock
  failures cannot alter checkpoint results, exception identity,
  compare-and-swap, commit, rollback, or caller-owned transaction behavior. No
  SDK/exporter dependency, migration, version bump, or release is included.
- Optional durable result-checkpoint store through
  `PostgresBatchResultCheckpointStore` and
  `llm_result_stream_checkpoints`, with tenant-qualified consumer identity,
  strict checkpoint revalidation, exact `expected_previous` compare-and-swap,
  idempotent repeats, locked reconciliation for concurrent first writers,
  caller-owned transaction methods for atomic local PostgreSQL effects, forced
  row-level security, byte-identical package/container migrations, a fail-closed
  rollback that refuses to erase acknowledgement evidence, deterministic live
  PostgreSQL and concurrency tests, and no false distributed exactly-once or
  unseen-suffix immutability claim. Version `0.1.0` remains unchanged.
- Immutable, versioned `BatchResultCheckpoint` and
  `CheckpointedBatchResultRecord` contracts plus opt-in
  `iter_checkpointed_batch_records()` and
  `open_checkpointed_batch_records()` APIs. Each checkpoint binds the exact
  validated batch and endpoint identity, ordered provider file kind and file
  identifier, physical and logical positions, raw line framing, and a
  domain-separated length-prefixed SHA-256 stream-prefix digest. Resume performs
  a fully bounded rescan from byte zero, suppresses acknowledged records only
  after exact checkpoint reproduction, and fails closed before later delivery
  on prefix mutation, file replacement, inserted or removed framing, or
  truncation at or before the checkpoint. This prefix evidence does not attest
  mutation or truncation strictly after the acknowledged checkpoint; hosts that
  require whole-stream immutability need a stable provider validator or a
  separate full-stream manifest. The host retains tenant authorization,
  tamper/rollback protection, and atomic sink/checkpoint responsibilities; no
  schema or release version change is included.
- Opt-in `StreamingBatchAPIClient` and immutable `BatchResultRecord` for
  output-then-error JSONL iteration without whole-body or whole-result-list
  materialization, with strict per-file decoded-byte, physical-line byte,
  batch-wide physical line, and combined record-count limits. Result and error
  files share the physical-line budget, and blank lines consume it before
  parsing; split UTF-8, CRLF, and final lines without a newline are handled
  deterministically, while invalid streams, encodings, JSON, non-object records,
  and non-success file responses fail closed with body-free diagnostics.
  `open_batch_records()` provides deterministic context-managed ownership for
  consumers that may stop before exhaustion.
- Read-only exact-head release acceptance that builds one wheel and source
  distribution twice from clean Git archives, proves byte-identical SHA-256
  identity, records bounded canonical evidence, and keeps publication and
  attestation authority separate.
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

- Required explicit nonblank checkpoint database targets for store construction
  and schema application, rejecting absent, empty, or whitespace-only DSNs
  before any Psycopg/libpq connection attempt instead of permitting ambient
  environment, service-file, or local-default target selection.
- Installed the durable checkpoint migration in the fresh bundled PostgreSQL image
  as `/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql`, after the cron
  initialization script, so new container deployments cannot silently omit the
  checkpoint persistence schema.
- Stopped idempotent GET retries at response handoff so post-handoff payload or
  response-close failures close once and cannot reopen provider files, duplicate
  already-yielded records, or violate the asynchronous-context-manager protocol.
- Closed active provider-file responses deterministically after context-managed
  early exits, explicitly closed nested asynchronous generators, rejected
  zero-progress empty adapter chunks, and removed provider-controlled decoder
  bytes and text from sanitized parser exception cause and context links.
- Bound release-directory traversal, artifact open, bounded streaming hash, size
  derivation, and final membership validation to held descriptors; reject parent
  symlinks, `..` traversal, artifact replacement, in-place identity drift, and
  unsupported no-follow runtimes before accepting reproducibility evidence.
- Replaced release-manifest pathname check-then-use writes with
  descriptor-relative no-follow traversal, exclusive temporary creation,
  descriptor-relative atomic rename, and file plus parent-directory
  synchronization, closing the time-of-check/time-of-use path-replacement window
  without granting release authority; version `0.1.0` remains unchanged.
- Bounded release-artifact directory enumeration to three entries, so a third
  unexpected artifact fails closed without materializing an unbounded output
  directory in verifier memory.
- Made missing and extra release-artifact count failures filesystem-order
  independent by omitting arbitrary sampled filenames from their diagnostics.
- Refused direct and nested parent symlinks before writing reproducible-release
  manifests, preventing pull-request-controlled workspace paths from redirecting
  the temporary file or atomic replacement outside the evidence directory.
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

- Bound repository CI checkouts to the exact pull-request source head and verify
  the checked-out commit before tests, coverage, packaging, or container gates.
- Exposed `ValidationError.field`, `.value`, and `.reason` as direct stable
  attributes while retaining the existing structured `details` dictionary.
- Migrated package licensing to PEP 639 with an SPDX `Apache-2.0` expression,
  explicit `LICENSE` and `NOTICE` files, the `uv_build` backend, and exact
  `uv`/`uv_build` 0.12.1 governed build pins so PEP 517 backend selection cannot
  drift independently of reviewed source.
- Consolidated immutable CI action, Python image, Rust toolchain image, and Ruff
  patch updates; setup-uv cache pruning is explicit to preserve the previous
  bounded cache-cost policy.

## [0.1.0] - 2026-07-12

### Added

- Initial standalone and embeddable PostgreSQL LLM batch engine extraction.
