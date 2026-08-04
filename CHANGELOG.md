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

### Changed

- Consolidated immutable CI action, Python image, Rust toolchain image, and Ruff patch updates; setup-uv cache pruning is explicit to preserve the previous bounded cache-cost policy.

### Fixed

- Retry-After parsing now rejects non-ASCII decimal digits and treats
  oversized ASCII deltas as excessive guidance without triggering Python
  integer-conversion limits.

## [0.1.0] - 2026-07-12

### Added

- Initial standalone and embeddable PostgreSQL LLM batch engine extraction.
