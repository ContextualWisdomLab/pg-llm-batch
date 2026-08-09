# HTTP 425 Too Early retry doctoring

## Purpose

This record documents why `pg-llm-batch` treats HTTP 425 `Too Early` as a bounded retry signal for idempotent provider GET operations, while preserving the single-attempt boundary for side-effecting POST operations, HTTP 500, and permanent TLS trust failures.

## Reviewed protocol and transport evidence

RFC 8470 defines 425 for requests that a server is unwilling to process because of replay risk from early data. It states that a user agent should retry automatically after a 425 response and that the automatic retry must not be sent in early data. The package's retry loop is already restricted to GET, which is an idempotent method under HTTP semantics, and the package does not deliberately enable early data for these provider requests.

RFC 9110 permits automatic retry of idempotent requests when a client knows a request can be repeated safely. It does not classify HTTP 500 as a dedicated temporary signal; 500 denotes an unexpected server condition. The project therefore does not infer that arbitrary 500 responses are retryable.

RFC 6585 defines 429 `Too Many Requests` and permits servers to include `Retry-After`, which is why the existing response-guided bounded-delay path remains shared by 425 and the other reviewed retry statuses.

aiohttp 3.14.3 exposes TLS handshake and certificate-verification failures through the `ClientSSLError` family. In particular, `ClientConnectorSSLError` and `ClientConnectorCertificateError` inherit from that family. aiohttp exposes certificate fingerprint mismatch separately as `ServerFingerprintMismatch`, a `ServerConnectionError` raised when the received peer certificate fingerprint does not match the configured expected fingerprint. Python's SSL documentation separately identifies certificate-verification failures as failures of peer certificate validation. These conditions are trust or TLS-policy evidence, not a provider overload signal, so blindly repeating the same request would not establish a safer peer identity.

## Package contract

The default retryable GET status set is exactly `{408, 425, 429, 502, 503, 504}`.

For those statuses, retry behavior remains bounded by `max_retry_attempts` and `retry_max_delay_seconds`. A valid `Retry-After` value within the configured maximum is honored. Otherwise the existing equal-jitter exponential fallback is used. The current response context is exited before the sleep and next request, so a retry does not retain the prior response resource.

TLS handshake and certificate failures are never retried automatically. An `aiohttp.ClientSSLError`, including a connector TLS handshake or certificate-verification error, fails after the first request-acquisition attempt and is translated to the existing bounded, body-free transport diagnostic. Certificate fingerprint mismatches are never retried automatically. An `aiohttp.ServerFingerprintMismatch` fails after the first request-acquisition attempt through the same bounded diagnostic path. Request-acquisition timeouts and other non-TLS `aiohttp.ClientError` failures retain the bounded GET retry path. This classification does not change response-status retries or create any POST replay path.

Provider uploads, batch creation, and batch cancellation are POST operations and remain single-attempt. HTTP 500 also remains single-attempt by default. Any future provider-specific 500 retry policy, or any proposal to retry TLS trust failures, requires a separate explicit contract, deterministic tests, and security/reliability review.

## Trust and security boundary

The package controls only its own application-level HTTP retry loop. It does not claim to configure or attest TLS 1.3 early-data negotiation in proxies, service meshes, gateways, operating-system TLS stacks, or upstream infrastructure. An embedding environment that enables early data must independently ensure that retry and replay semantics remain safe.

Failing closed on `ClientSSLError` and `ServerFingerprintMismatch` is a transport policy boundary, not a replacement for platform trust-store or certificate-pinning governance. The package does not suppress, rewrite, or automatically bypass certificate or fingerprint validation. The exported `GatewayError` retains a bounded exception type and timeout value rather than provider-controlled exception text, endpoint hostnames, or fingerprint bytes.

The response-status retry decision uses only the HTTP status and bounded `Retry-After` guidance. Provider response bodies do not decide whether a request is replayed. Existing credential, HTTPS, no-redirect, response-size, body-confidentiality, and post-response-handoff no-replay controls remain unchanged.

## Operational behavior

A 425 received on a safe GET is released and retried while attempts remain. Operators should expect the same bounded delay metrics and warning logs already emitted for the established retryable GET statuses. If attempts are exhausted, or valid `Retry-After` guidance exceeds the configured maximum, the response is exposed to the normal caller path rather than retried indefinitely.

A TLS handshake, certificate-verification, or certificate fingerprint mismatch produces one GET attempt and zero retry sleeps. Operators should treat that result as a trust, certificate, peer-identity, protocol, or TLS-policy incident to diagnose rather than increasing retry counts. A request-acquisition timeout remains eligible for the existing bounded idempotent GET retry policy.

A 500 response is exposed immediately. Operators should not compensate by increasing the global retry set without evidence that a specific provider contract makes that replay safe and useful.

## Recovery and rollback

No persistent state, schema, migration, background job, credential, or trust-store change is involved. Operational recovery for TLS failures is to correct the endpoint certificate, trust chain, hostname, configured fingerprint, proxy/service-mesh TLS policy, or other deployment cause and then issue a new caller-controlled request. The client does not retry around the failure automatically.

Rollback consists of removing 425 from the closed retry set and reverting the associated retry-classification tests and documentation. In-flight requests are not migrated or reconstructed. Reintroducing automatic TLS retries is not a routine rollback step; it requires a separately reviewed security contract.

## Verification

Permanent regression coverage requires that:

- 425 on GET releases the first response and retries through the existing bounded delay path;
- the exact default status set is `{408, 425, 429, 502, 503, 504}`;
- HTTP 500 remains outside that set and is single-attempt;
- TLS connector handshake and certificate-verification failures each perform exactly one GET and zero retry sleeps;
- certificate fingerprint mismatch performs exactly one GET and zero retry sleeps while exporting no peer hostname or fingerprint bytes;
- request-acquisition timeouts retain one bounded retry under the configured attempt policy;
- public, contributor, changelog, ADR, and doctoring text all state the same fail-closed TLS boundary; and
- the existing project gates continue to prove 100% production statement and branch coverage plus 100% public docstrings.

## References

aiohttp contributors. (2026). *Client exceptions*. aiohttp 3.14.3 documentation. https://docs.aiohttp.org/en/stable/_modules/aiohttp/client_exceptions.html

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://www.rfc-editor.org/rfc/rfc9110.html

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes* (RFC 6585). RFC Editor. https://www.rfc-editor.org/rfc/rfc6585.html

Python Software Foundation. (2026). *ssl—TLS/SSL wrapper for socket objects*. Python 3.14 documentation. https://docs.python.org/3.14/library/ssl.html

Thomson, M., Nottingham, M., & Schinazi, D. (2018). *Using early data in HTTP* (RFC 8470). RFC Editor. https://www.rfc-editor.org/rfc/rfc8470.html