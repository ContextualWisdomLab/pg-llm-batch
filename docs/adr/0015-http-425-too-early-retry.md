# ADR 0015: Retry HTTP 425 Too Early only for bounded idempotent GETs

- **Status:** Accepted for the bounded retry slice
- **Date:** 2026-08-08

## Context

`BatchAPIClient` retries a deliberately closed set of transient responses only for GET requests. Side-effecting POST operations, including uploads, batch creation, and cancellation, are intentionally single-attempt.

RFC 8470 defines HTTP 425 `Too Early` as a server signal that a request should be retried without early data. It also states that a user agent should retry a request automatically after receiving 425, while the automatic retry must not itself be sent in early data. This package does not deliberately opt provider Batch API calls into TLS/HTTP early data, and its retry loop is already restricted to idempotent GET operations.

HTTP 500 is different. RFC 9110 defines 500 as an unexpected server condition, not an explicit temporary or rate-limit signal. Automatically treating every 500 as transient would broaden replay policy without a provider-specific contract.

The transport-exception boundary also needs to distinguish request-acquisition failures that can plausibly improve on another bounded attempt from failures that indicate a TLS trust or policy problem. aiohttp exposes certificate-verification and TLS handshake failures through the `ClientSSLError` family. It exposes a certificate fingerprint mismatch separately as `ServerFingerprintMismatch`, which is a peer-identity failure rather than an overload condition. Repeating the same request must not be used as an automatic way to work around peer identity, certificate validation, fingerprint validation, or TLS policy failures.

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

TLS handshake and certificate failures are never retried automatically. Any `aiohttp.ClientSSLError`, including `ClientConnectorSSLError` and `ClientConnectorCertificateError`, crosses the fail-closed transport boundary after the first acquisition attempt and is translated to the existing bounded `GatewayError`. Certificate fingerprint mismatches are never retried automatically; `aiohttp.ServerFingerprintMismatch` crosses the same fail-closed boundary after the first acquisition attempt. Request-acquisition timeouts and other non-TLS `aiohttp.ClientError` failures retain the existing bounded idempotent-GET retry behavior.

The library does not claim to control TLS early-data negotiation performed outside its HTTP client boundary. Operators or embedding gateways that enable early data remain responsible for ensuring replay safety at that layer.

## Consequences

The change aligns an omitted protocol-defined retry signal with the package's existing idempotent GET retry boundary without widening side-effecting request replay. A provider that legitimately returns 425 for a GET receives a bounded retry instead of an immediate application-level failure. Generic 500 responses continue to surface to the caller without automatic replay.

Certificate-verification, TLS handshake, and certificate fingerprint failures surface after one request attempt instead of being hidden behind repeated connection attempts. This preserves a fail-closed trust boundary and keeps operational evidence attributable to the original TLS failure class without exposing provider-controlled exception text, endpoint hostnames, or fingerprint bytes.

Permanent regression tests freeze the closed HTTP status set, keep HTTP 500 single-attempt, prove TLS handshake, certificate-verification, and certificate fingerprint failures perform one GET with zero retry sleeps, and prove request-acquisition timeouts remain retryable. Existing 100% production statement and branch coverage, public-docstring, security, and packaging gates remain unchanged.

## Rollback

Rollback is code-only: remove 425 from `RETRYABLE_GET_STATUSES` and revert the TLS classification, ADR, doctoring, changelog, and regression contracts. No database migration, durable state conversion, credential rotation, or provider-side cleanup is required. Reintroducing automatic TLS retries would require a separate reviewed threat model and deterministic tests rather than being part of routine rollback.

## References

aiohttp contributors. (2026). *Client exceptions*. aiohttp 3.14.3 documentation. https://docs.aiohttp.org/en/stable/_modules/aiohttp/client_exceptions.html

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://www.rfc-editor.org/rfc/rfc9110.html

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes* (RFC 6585). RFC Editor. https://www.rfc-editor.org/rfc/rfc6585.html

Python Software Foundation. (2026). *ssl—TLS/SSL wrapper for socket objects*. Python 3.14 documentation. https://docs.python.org/3.14/library/ssl.html

Thomson, M., Nottingham, M., & Schinazi, D. (2018). *Using early data in HTTP* (RFC 8470). RFC Editor. https://www.rfc-editor.org/rfc/rfc8470.html