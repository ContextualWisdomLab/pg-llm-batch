# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- Enforced the lifecycle schema's 128-character endpoint-alias and 256-character
  remote-resource identifier boundaries before order reservation, credential
  resolution, provider calls, custom lifecycle recorders, or PostgreSQL writes.
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
