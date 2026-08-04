# Bounded Idempotent GET Retries Design

## Context

The client currently turns transport failures into `GatewayError` immediately and returns provider `429`, `502`, `503`, and `504` responses to callers without retrying. A transient gateway overload, connection reset, or upstream timeout therefore fails a poll or result retrieval even when an immediate bounded retry would succeed.

Blind retries are unsafe for the Files and Batches APIs because `POST /files`, `POST /batches`, and cancellation requests can produce side effects or duplicate cost. The improvement must retry only methods whose semantics are safe and idempotent in this client.

RFC 9110 defines `Retry-After` as either an HTTP-date or a non-negative decimal delay in seconds. RFC 6585 permits `429 Too Many Requests` responses to carry `Retry-After`. The client should respect a valid bounded value while refusing attacker-controlled waits beyond the configured retry delay budget.

## Selected approach

Extend `BatchAPIClient._request()` with an internal retry loop that is active only for `GET` requests.

The default policy is:

- maximum total attempts: 3;
- base fallback delay: 0.5 seconds;
- maximum individual delay: 30 seconds;
- retryable statuses: `408`, `429`, `502`, `503`, and `504`;
- retryable transport failures: `aiohttp.ClientError` and `asyncio.TimeoutError`;
- fallback schedule: equal-jitter exponential backoff between one-half and the full capped exponential delay;
- valid `Retry-After`: use the requested delay exactly when it is within the configured maximum;
- excessive `Retry-After`: do not retry, so an untrusted server cannot force an excessive sleep;
- malformed `Retry-After`: use bounded equal-jitter fallback;
- final attempt: yield the response or raise the existing structured transport error.

All `POST` requests remain single-attempt, including upload, batch creation, and cancellation. This prevents ambiguous replay and duplicate remote work.

## Public interface

`BatchAPIClient.__init__()` gains three keyword-only options:

```python
max_retry_attempts: int = 3
retry_base_delay_seconds: float = 0.5
retry_max_delay_seconds: float = 30.0
```

Validation rules:

- `max_retry_attempts` is a positive non-boolean integer;
- delay values are finite non-boolean numbers greater than or equal to zero;
- `retry_base_delay_seconds` must not exceed `retry_max_delay_seconds`.

The client stores normalized floats and the integer attempt limit.

## Retry-After parsing

A private helper parses a response header using the RFC grammar:

1. trim optional surrounding whitespace;
2. if the value contains only decimal digits, return that non-negative delay;
3. otherwise parse it as an HTTP-date with `email.utils.parsedate_to_datetime`;
4. interpret a timezone-naive parsed date as UTC defensively;
5. return the non-negative difference from the current UTC time;
6. return `None` for malformed values.

The clock is isolated behind `_utc_now()` so HTTP-date behavior is deterministic in tests.

## Request flow

For each request:

1. resolve the session and method once;
2. start attempt 1;
3. enter the aiohttp response context;
4. for a retryable `GET` response before the final attempt, calculate the delay;
5. if the delay is allowed, exit the response context, sleep, increment the attempt, and retry;
6. otherwise yield the response to the existing caller logic;
7. for a retryable transport exception before the final attempt, sleep using fallback backoff and retry;
8. after the final transport failure, raise the existing typed `GatewayError` contract.

The response context is always exited before sleeping, allowing aiohttp to release the connection.

## Error and observability contract

Existing final provider-status and transport errors remain source-compatible. Retry metadata is logged at warning level but API keys, response bodies, and authorization headers are never logged.

Each retry log records only:

- operation;
- attempt number and configured maximum;
- response status or exception type;
- bounded delay.

## Alternatives considered

### Retry every request

This would improve apparent availability but risks duplicate file uploads, duplicate batch jobs, duplicate cancellation effects, and duplicate provider charges. It is rejected.

### Require callers to implement retries

This preserves a smaller client but causes inconsistent policies, repeated parsing bugs, and poor interoperability with provider `Retry-After` guidance. The shared client is the correct boundary.

### Use a third-party retry library

A new dependency would add supply-chain and configuration surface for a small, auditable policy. The standard library and existing asyncio/aiohttp stack are sufficient.

### Retry indefinitely

Unbounded retrying hides persistent failures, prevents operator control, and can amplify outages. The policy is deliberately finite.

## Testing

Tests cover:

- constructor option validation;
- delta-seconds and HTTP-date `Retry-After` parsing;
- malformed and past-date handling;
- equal-jitter fallback boundedness;
- retryable GET status followed by success;
- retryable transport failures followed by success;
- final-attempt behavior;
- excessive `Retry-After` refusing to sleep or retry;
- POST status and transport failures remaining single-attempt;
- no change to request timeout and redirect policy;
- 100% production statement and branch coverage.

## Documentation and release handling

README documents the retry defaults, safe-method boundary, and operator overrides. `CHANGELOG.md` records the feature under `Unreleased`. No release is published until the integrated exact head passes CI, SAST, Security Scan, packaging, review, provenance, and release-acceptance gates.