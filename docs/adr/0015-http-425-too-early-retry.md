# ADR 0015: Retry HTTP 425 Too Early only for bounded idempotent GETs

- **Status:** Accepted for the bounded retry slice
- **Date:** 2026-08-08

## Context

`BatchAPIClient` already retries a deliberately closed set of transient responses only for GET requests. The existing set is 408, 429, 502, 503, and 504. Side-effecting POST operations, including uploads, batch creation, and cancellation, are intentionally single-attempt.

RFC 8470 defines HTTP 425 `Too Early` as a server signal that a request should be retried without early data. It also states that a user agent should retry a request automatically after receiving 425, while the automatic retry must not itself be sent in early data. This package does not deliberately opt provider Batch API calls into TLS/HTTP early data, and its retry loop is already restricted to idempotent GET operations.

HTTP 500 is different. RFC 9110 defines 500 as an unexpected server condition, not an explicit temporary or rate-limit signal. Automatically treating every 500 as transient would broaden replay policy without a provider-specific contract.

## Decision

The default retryable GET status set is exactly:

`{408, 425, 429, 502, 503, 504}`.

HTTP 425 uses the same bounded retry machinery as the other reviewed GET statuses:

1. The first response context is released before retry sleep.
2. `Retry-After`, when valid and within the configured maximum delay, takes precedence.
3. Otherwise the existing bounded equal-jitter exponential fallback applies.
4. Total attempts remain bounded by `max_retry_attempts`.
5. POST operations remain single-attempt.
6. HTTP 500 remains outside the default retry set unless a future explicit provider contract is reviewed and tested separately.

The library does not claim to control TLS early-data negotiation performed outside its HTTP client boundary. Operators or embedding gateways that enable early data remain responsible for ensuring replay safety at that layer.

## Consequences

The change aligns an omitted protocol-defined retry signal with the package's existing idempotent GET retry boundary without widening side-effecting request replay. A provider that legitimately returns 425 for a GET receives a bounded retry instead of an immediate application-level failure. Generic 500 responses continue to surface to the caller without automatic replay.

The new status is covered by deterministic regression tests that also freeze the closed retry set and keep HTTP 500 single-attempt. Existing 100% production statement and branch coverage, public-docstring, security, and packaging gates remain unchanged.

## Rollback

Rollback is code-only: remove 425 from `RETRYABLE_GET_STATUSES` and revert this ADR, doctoring, changelog, and regression contract. No database migration, durable state conversion, credential rotation, or provider-side cleanup is required.

## References

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://www.rfc-editor.org/rfc/rfc9110.html

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes* (RFC 6585). RFC Editor. https://www.rfc-editor.org/rfc/rfc6585.html

Thomson, M., Nottingham, M., & Schinazi, D. (2018). *Using early data in HTTP* (RFC 8470). RFC Editor. https://www.rfc-editor.org/rfc/rfc8470.html
