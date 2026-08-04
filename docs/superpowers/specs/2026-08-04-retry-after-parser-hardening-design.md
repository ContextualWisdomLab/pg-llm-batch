# Retry-After Parser Hardening Design

## Context

`BatchAPIClient` retries transient idempotent provider `GET` requests and honors a bounded `Retry-After` value. The current delta-seconds branch uses:

```python
if candidate.isdecimal():
    return float(int(candidate))
```

That implementation has two hostile-input problems at an external HTTP boundary:

1. Python's `str.isdecimal()` accepts Unicode decimal characters, while RFC 9110 defines `delay-seconds` as `1*DIGIT`, where HTTP ABNF `DIGIT` is the ASCII range `0` through `9`.
2. Python deliberately limits decimal string-to-integer conversion. A provider-controlled decimal string longer than the interpreter's configured limit raises `ValueError` before the client can apply its bounded retry policy. Very large integers can also overflow when converted to `float`.

A malformed or adversarial response header must not escape as an untyped Python exception or broaden the accepted HTTP grammar.

## Goals

- Accept RFC 9110 delta-seconds only when every character is ASCII `0` through `9`.
- Parse arbitrarily long syntactically valid delta-seconds without invoking Python's bounded decimal-to-`int` conversion.
- Preserve bounded retry behavior: values above `retry_max_delay_seconds` disable that retry rather than forcing or truncating an untrusted wait.
- Preserve HTTP-date parsing and malformed-value fallback behavior.
- Keep the change isolated to the retry parser and its tests, documentation, and changelog.
- Retain 100% production statement, branch, and docstring coverage on Python 3.10, 3.12, and 3.14.

## Non-goals

- Changing which HTTP statuses are retryable.
- Retrying side-effecting `POST` operations.
- Changing attempt counts or jitter defaults.
- Introducing arbitrary header-length limits into the general HTTP client.
- Replacing `email.utils.parsedate_to_datetime` for HTTP-date handling.

## Approaches considered

### 1. ASCII validation plus direct floating-point parsing — selected

Require `candidate.isascii() and candidate.isdigit()`, then parse with `float(candidate)`.

For ordinary bounded values, decimal integers below the configured retry ceiling are exactly usable for delay comparison and sleeping. Extremely large ASCII digit strings convert to positive infinity rather than exercising Python's decimal-to-integer digit limit. The existing `retry_after > retry_max_delay_seconds` check then refuses the retry. No untrusted value is shortened or used as a sleep duration.

This is the smallest implementation that matches the RFC grammar and preserves the existing safety policy.

### 2. Length cap followed by `int()`

Reject decimal strings above a fixed digit count before calling `int()`.

This avoids the interpreter limit but introduces an arbitrary grammar restriction unrelated to the configured retry budget. It also duplicates a parser limit that can drift from Python or deployment policy.

### 3. Decimal-string comparison against the configured maximum

Normalize leading zeros and compare the digit string against a decimal representation of `retry_max_delay_seconds` without numeric conversion.

This avoids floating-point conversion, but it couples parsing to client configuration, complicates fractional configured maxima, and adds unnecessary comparison machinery for a maximum delay that is already represented as a float.

## Selected contract

`_parse_retry_after(value, now)` behaves as follows:

- non-string, empty, signed, fractional, Unicode-decimal, or otherwise malformed values return `None`;
- ASCII decimal digits return `float(candidate)`;
- an extremely large ASCII decimal value may return positive infinity;
- valid HTTP-date values continue to return a non-negative delay relative to `now`;
- malformed HTTP dates return `None`.

`_retry_delay_for_response()` retains ownership of policy enforcement:

- finite values at or below `retry_max_delay_seconds` are honored exactly;
- values above the maximum, including positive infinity, return `None` and therefore refuse that retry;
- malformed values select the existing bounded equal-jitter fallback.

## Security and failure behavior

The provider controls `Retry-After`, so parsing is fail-closed with respect to waiting:

- syntactically valid but excessive guidance is never truncated to the local maximum;
- malformed guidance cannot trigger an unbounded or provider-selected sleep;
- hostile numeric length cannot leak `ValueError` or `OverflowError` through the gateway boundary;
- Unicode lookalike digits are not treated as HTTP `DIGIT` tokens.

No response body or credential data is added to errors or logs.

## Testing

Add focused tests that first fail against the current parser:

1. a decimal value longer than Python's default integer digit limit does not raise and causes a retryable response to be returned without sleep or replay;
2. Arabic-Indic and fullwidth decimal strings are rejected by the parser;
3. rejected Unicode decimal guidance uses the existing bounded fallback retry path;
4. ordinary ASCII delta-seconds and HTTP-date behavior remain unchanged.

Run the complete non-integration suite, Ruff, Interrogate, 100% statement and branch coverage, lockfile verification, package build, and container builds through repository CI.

## Documentation and release handling

README will state explicitly that delta-seconds follow the RFC ASCII-digit grammar and that syntactically valid values above the configured maximum are refused. `CHANGELOG.md` will record the parser hardening under `Unreleased / Fixed`.

This focused hardening does not publish a release by itself. A release remains gated on the integrated unreleased feature set, exact-head CI and security evidence, release provenance, and an explicit versioning decision.

## Standards basis

- RFC 9110, Section 10.2.3, defines `Retry-After = HTTP-date / delay-seconds` and `delay-seconds = 1*DIGIT`.
- Python documents a configurable security limit for non-power-of-two integer string conversion and raises `ValueError` when decimal input exceeds that limit.
