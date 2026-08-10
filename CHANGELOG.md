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

- Released orchestrator-owned and CLI-owned configuration, secret, and
  token-counting PostgreSQL connections deterministically after successful,
  failed, and partially constructed operations; each partially initialized
  store constructor now closes an acquired connection when setup fails; and
  token configuration is validated before acquiring the cached `pg_tiktoken`
  session.
- `TokenCounter.buffer_percentage` is now an **exact integer** from **0 through
  50** and is validated **before PostgreSQL** extension setup or cached
  token-counting connection acquisition; booleans, floats, strings, and
  container values fail with bounded `ValidationError` instead of being
  accepted or producing unrelated type failures.
- Configured `TokenCounter` hard ceilings `token_limits.per_batch`,
  `token_limits.per_request`, `azure_limits.max_records_per_file`,
  `azure_limits.max_bytes_per_file`, and `azure_limits.max_files_per_job` now
  require an **exact positive integer** **before PostgreSQL** extension/session
  acquisition; booleans, zero, negative integers, floats, strings, and
  containers fail with bounded `ValidationError` instead of implicit coercion
  or unrelated arithmetic errors. Buffered `per_batch` limits now use integer
  arithmetic end-to-end rather than float conversion, avoiding precision loss
  and overflow for very large exact integer ceilings.
- `BatchAccumulator.max_records` and `BatchAccumulator.max_bytes` now require an
  **exact positive integer** after explicit/configured selection. **Explicit
  zero** no longer behaves like omission and cannot silently select a larger
  **configured default**; malformed configured defaults fail closed before any
  JSONL record is accumulated.
- A configured Fernet encryption key must now fail closed when the optional
  `cryptography` dependency is unavailable instead of silently downgrading the
  explicit encryption request to base64 obfuscation; the intentional no-key
  local/dev fallback remains unchanged.
- Rejected malformed persisted local/dev Base64 secret values with strict
  alphabet, padding, and UTF-8 validation; failures expose only a bounded
  `ConfigError` and do not retain stored credential material through exception
  cause or context.
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