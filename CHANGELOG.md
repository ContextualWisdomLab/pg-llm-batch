# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Read-only exact-head release acceptance that builds wheel and source distribution artifacts twice from clean Git archives, proves byte-identical SHA-256 identity, records bounded canonical evidence, and keeps publication and attestation authority separate.
- Optional bounded provider output/error-file lifetime controls for batch creation, with exact local validation before credential resolution and backward-compatible omission for provider-neutral callers.
- Trusted tenant-scoped durable lifecycle identities for shared-table MSA deployments, including `TenantDurableBatchAPIClient`, tenant-qualified persistence and read helpers, transaction-local PostgreSQL context, forced default-deny row-level security, and explicit standalone compatibility.
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
  HTTP 425 `Too Early`, RFC `Retry-After` support, and equal-jitter exponential
  fallback. TLS handshake and certificate failures are never retried
  automatically. Certificate fingerprint mismatches are never retried
  automatically. Side-effecting POST operations and HTTP 500 remain
  single-attempt by default.
- Durable remote batch lifecycle persistence through `DurableBatchAPIClient`
  and `llm_remote_batch_jobs`, with database-owned pre-request observation
  ordering, immutable terminal status identity, bounded curated metadata, and
  structured reservation/persistence recovery evidence.

### Fixed

- Bound release-artifact traversal, hashing, identity validation, and manifest publication to descriptor-relative no-follow operations with bounded enumeration, atomic replacement, and file plus parent-directory synchronization so symlink or same-name replacement cannot convert a verified artifact set into different release evidence; this closes the documented time-of-check/time-of-use boundary while version `0.1.0` remains unchanged.
- Rejected non-callable standalone and tenant lifecycle recorders or observation reservers during client construction, before any provider operation can succeed without a usable persistence path.
- Made the tenant lifecycle migration atomic across owner-enforcement relaxation, legacy-row backfill, constraint replacement, and forced-RLS restoration so psql autocommit cannot commit an intermediate owner-bypass state.
- Bootstrap DSN and Fernet-key source selection now consults process environment
  only when the corresponding explicit argument is omitted. Explicit Postgres
  DSNs must be exact nonblank strings, explicit Fernet keys must be exact
  strings, and an explicit empty Fernet key remains empty instead of silently
  inheriting ambient decryption authority.
- Restricted the bundled standalone Compose PostgreSQL and component-health
  published ports to IPv4 loopback so the default developer profile no longer
  listens on every host interface when operators have not made an explicit
  ingress decision.
- Removed plaintext secret values from `config set-secret` process arguments;
  interactive entry now uses a no-echo prompt and fails closed if terminal echo
  suppression is unavailable. Automation accepts one bounded logical line over
  standard input, removes only one terminal LF/CRLF framing sequence, and rejects
  vertical tab, form feed, ASCII file/group/record separators, Unicode Next Line,
  U+2028, and U+2029 before `SecretStore` construction. Rejected legacy argv
  values remain redacted from parser diagnostics instead of being reflected into
  logs or captured stderr.
- `BatchAPIClient.wait_for_batch()` now requires `poll_interval_seconds` and
  `timeout_seconds` to be finite positive numeric durations before credential
  resolution or provider I/O, rejecting booleans, strings, `None`, NaN,
  infinities, zero, and negative values before they can create invalid deadlines,
  sleeps, or unrelated transport/type failures.
- Batch status responses now fail closed with `InvalidBatchStatusPayload` when
  the provider does not return a **non-empty status string**, when
  `request_counts` is not an object, when `total`, `completed`, or `failed` is
  not a **non-negative integer**, or when `completed + failed` exceeds `total`;
  malformed provider values are not copied into exported diagnostics.
- Provider HTTP error responses no longer export provider-controlled JSON,
  free-text bodies, debug fields, or cancellation messages through package
  diagnostics. Files upload, batch creation/status, and file download expose
  only the status plus fixed `ProviderHTTPError`; cancellation rejection exposes
  only the status plus the fixed package reason.
- Malformed successful provider responses now fail with fixed bounded package
  diagnostics without retaining provider bytes, decoded text, or parser/decoder
  exceptions; malformed provider response exception links are removed from the
  exported `GatewayError` cause/context chain.
- Dependency-defined transport exception class names never enter exported
  diagnostics or retry warning logs; acquisition failures use the closed
  `ServerFingerprintMismatch`, `ClientConnectorCertificateError`,
  `ClientSSLError`, `TimeoutError`, or `ClientError` vocabulary.
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
- Migrated package licensing to PEP 639 with an SPDX `Apache-2.0` expression,
  explicit `LICENSE` and `NOTICE` files, and a compatible setuptools backend
  floor so built artifacts expose normalized legal metadata without warnings.
- Consolidated immutable CI action, Python image, Rust toolchain image, and Ruff
  patch updates; setup-uv cache pruning is explicit to preserve the previous
  bounded cache-cost policy.

## [0.1.0] - 2026-07-12

### Added

- Initial standalone and embeddable PostgreSQL LLM batch engine extraction.
