# Hostile Retry-After Parser Hardening Design

## Context

`BatchAPIClient` retries idempotent provider `GET` requests and interprets the
HTTP `Retry-After` field as either delta seconds or an HTTP date. The current
delta parser uses:

```python
if candidate.isdecimal():
    return float(int(candidate))
```

That expression has two boundary defects at the untrusted HTTP header seam.
First, Python's Unicode-aware `str.isdecimal()` accepts non-ASCII decimal
characters such as fullwidth digits, although RFC 9110 defines
`delay-seconds = 1*DIGIT`, where the ABNF `DIGIT` terminal is ASCII. Second,
converting an excessively long decimal string through `int()` can raise
Python's bounded integer-conversion `ValueError` before the configured retry
delay ceiling can reject the value. A provider can therefore turn malformed or
extreme guidance into an implementation exception instead of the documented
bounded retry behavior.

## Selected approach

Keep the existing public API and change only the pure parser boundary:

```python
if candidate.isascii() and candidate.isdecimal():
    return float(candidate)
```

The ASCII predicate enforces the RFC grammar. Direct floating-point conversion
avoids Python's decimal-to-integer digit limit; values beyond the floating-point
range become positive infinity. The existing
`retry_after > retry_max_delay_seconds` comparison then refuses the retry and
returns the original provider response to the caller without sleeping or
replaying the request.

This is preferable to introducing an arbitrary header digit-count limit because
it preserves all valid finite decimal values and reuses the already documented
maximum-delay policy as the single operational bound.

## Alternatives considered

### Catch `ValueError` around `int()`

Catching the exception closes the crash but leaves the Unicode grammar defect
and introduces a second policy decision for oversized values. It is rejected.

### Limit decimal strings to a fixed number of digits

A fixed digit limit is easy to reason about but would be an implementation
constraint not derived from the protocol or the existing retry budget. It is
unnecessary because direct float conversion and the maximum-delay comparison
already fail closed.

### Treat oversized values as malformed and use fallback jitter

Falling back would retry sooner than the server explicitly requested. For
untrusted excessive guidance, the current policy intentionally refuses the
retry rather than shortening the requested wait. That behavior remains
unchanged.

## Contract

The parser must satisfy all of the following:

1. ASCII decimal strings produce a non-negative float.
2. ASCII strings too large for a finite float produce positive infinity and
   are consequently refused by the configured maximum-delay policy.
3. Non-ASCII decimal characters are not accepted as `delay-seconds` and select
   the existing malformed-header fallback path.
4. HTTP-date parsing and past-date clamping remain unchanged.
5. No provider header content appears in raised error metadata or logs.
6. POST operations remain single-attempt.
7. Production statement, branch, and docstring coverage remain 100%.
8. Python 3.10, 3.12, and 3.14 remain supported.

## Testing

A focused regression module will prove the pre-fix behavior is red and then
cover:

- a 5,000-digit ASCII delta returning positive infinity rather than raising;
- fullwidth decimal digits returning `None`;
- the existing excessive-guidance path returning the provider response without
  sleeping or replaying;
- all existing Retry-After, GET retry, transport, and POST non-retry tests.

The full non-integration suite, compile check, Ruff, Interrogate, 100% statement
and branch coverage, lockfile check, and package build must pass on the exact
feature head before review and merge.

## Documentation and release handling

README will say "ASCII delta" to make the wire grammar explicit. CHANGELOG will
record the hostile-header fix under `Unreleased / Fixed`. This narrow hardening
slice does not publish a release by itself; release evaluation occurs only after
its reviewed exact head is integrated with all required repository gates.
