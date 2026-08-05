# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Opt-in OpenTelemetry spans, operation counts, and duration histograms for all
  public Batch API client operations, with explicit tracer/meter injection,
  lazy global-provider resolution, bounded error and cancellation
  classification, a strict no-identifiers/no-payload telemetry contract, and
  fail-open isolation when tracer or metric providers are unavailable.
- Bounded, streamed provider result and error downloads with a 128 MiB
  decoded-byte default, strict UTF-8 validation, body-free oversize errors,
  and fail-closed handling when a bounded byte stream is unavailable.
- Bounded retries for transient idempotent provider GET failures, including
  RFC Retry-After support and equal-jitter exponential fallback; side-effecting
  POST operations remain single-attempt.

### Fixed

- Hardened provider `Retry-After` delta parsing to accept RFC ASCII digits only
  and refuse extremely long numeric guidance without leaking Python integer
  conversion errors.

### Changed

- Migrated package licensing to PEP 639 with an SPDX `Apache-2.0` expression, explicit `LICENSE` and `NOTICE` files, and a compatible setuptools backend floor so built artifacts expose normalized legal metadata without warnings.
- Consolidated immutable CI action, Python image, Rust toolchain image, and Ruff patch updates; setup-uv cache pruning is explicit to preserve the previous bounded cache-cost policy.

## [0.1.0] - 2026-07-12

### Added

- Initial standalone and embeddable PostgreSQL LLM batch engine extraction.
