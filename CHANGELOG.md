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

- Refreshed immutable CI action pins for `actions/checkout` 7.0.1,
  `actions/setup-python` 7.0.0, `astral-sh/setup-uv` 9.0.0, and
  `step-security/harden-runner` 2.20.0. The workflow explicitly keeps cache
  pruning enabled so the setup-uv major upgrade does not increase cache use.
- Refreshed the pinned Python and Rust container digests and updated the
  development Ruff toolchain to 0.16.1 with a regenerated lockfile.

## [0.1.0] - 2026-07-12

### Added

- Initial standalone and embeddable PostgreSQL LLM batch engine extraction.
