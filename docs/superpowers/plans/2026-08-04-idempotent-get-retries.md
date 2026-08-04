# Bounded Idempotent GET Retries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover safely from transient provider and transport failures for idempotent GET operations without replaying side-effecting POST requests.

**Architecture:** Add validated retry options and a finite retry loop to `BatchAPIClient._request()`. Parse RFC-compliant `Retry-After` values, use bounded equal-jitter exponential fallback, release each failed response context before sleeping, and keep POST operations single-attempt.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, `email.utils`, `datetime`, `random`, pytest, pytest-asyncio, pytest-cov, Ruff, Interrogate.

## Global Constraints

- Maximum total attempts default to exactly `3`.
- Fallback base delay defaults to exactly `0.5` seconds.
- Individual retry delay defaults to a maximum of exactly `30.0` seconds.
- Retryable statuses are exactly `408`, `429`, `502`, `503`, and `504`.
- Only GET requests are retried.
- POST uploads, batch creation, and cancellation remain single-attempt.
- `Retry-After` accepts only non-negative decimal seconds or HTTP-date.
- A valid `Retry-After` above the configured maximum disables that retry rather than shortening an attacker-controlled wait.
- Fallback delay uses equal jitter within one-half to the full capped exponential delay.
- Existing final error shapes remain compatible.
- Added production code must retain 100% statement, branch, and docstring coverage.
- Python 3.10, 3.12, and 3.14 remain supported.

---

### Task 1: Define retry policy behavior

**Files:**
- Create: `tests/test_idempotent_get_retries.py`
- Modify: `tests/test_http_transport.py`

**Interfaces:**
- Consumes: `BatchAPIClient`, `GatewayCredentials`, `GatewayError`, and `ValidationError`.
- Produces: failing tests for retry configuration, RFC `Retry-After`, status retries, transport retries, final attempts, and non-retried POST operations.

- [ ] **Step 1: Add response and sequence session doubles**

```python
class Response:
    def __init__(self, status: int, payload: dict, headers: dict[str, str] | None = None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def json(self):
        return self.payload
```

A sequence session returns or raises configured outcomes and records method, URL, and kwargs.

- [ ] **Step 2: Write failing constructor validation tests**

Cover invalid attempt counts, invalid delay values, and `base > max`.

- [ ] **Step 3: Write failing Retry-After tests**

Cover:

```text
Retry-After: 2
Retry-After: Wed, 21 Oct 2015 07:28:00 GMT
Retry-After: malformed
Retry-After: a date in the past
Retry-After larger than retry_max_delay_seconds
```

- [ ] **Step 4: Write failing GET retry tests**

Require:

```text
503 -> 200 retries once
429 with Retry-After -> 200 sleeps exactly as directed
transport error -> 200 retries
three retryable responses stop at max attempts and return final status error
```

- [ ] **Step 5: Write failing POST non-retry tests**

Verify both provider status and transport failures make exactly one POST attempt.

- [ ] **Step 6: Commit the red contract and open a draft PR**

The expected exact-head failure is missing retry constructor parameters and one-attempt behavior.

### Task 2: Implement the bounded retry policy

**Files:**
- Modify: `pg_llm_batch/batch_api_client.py`
- Test: `tests/test_idempotent_get_retries.py`
- Modify: `tests/test_http_transport.py`

**Interfaces:**
- Consumes: aiohttp response-like contexts and existing request operations.
- Produces: retry constants, constructor options, `_utc_now()`, `_parse_retry_after()`, `_fallback_retry_delay()`, `_retry_delay_for_response()`, and retry-aware `_request()`.

- [ ] **Step 1: Add imports and constants**

```python
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DEFAULT_MAX_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5
DEFAULT_RETRY_MAX_DELAY_SECONDS = 30.0
RETRYABLE_GET_STATUSES = frozenset({408, 429, 502, 503, 504})
```

- [ ] **Step 2: Add pure parsing helpers**

```python
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_retry_after(value: Any, now: datetime) -> Optional[float]:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate.isdecimal():
        return float(int(candidate))
    try:
        parsed = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delay = (parsed.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()
    return max(0.0, delay)
```

- [ ] **Step 3: Validate constructor options**

Normalize numeric delays to float and reject non-finite, boolean, negative, and inconsistent values with field-specific `ValidationError`.

- [ ] **Step 4: Add bounded equal-jitter fallback**

```python
ceiling = min(
    self.retry_base_delay_seconds * (2 ** (failed_attempt - 1)),
    self.retry_max_delay_seconds,
)
return random.uniform(ceiling / 2, ceiling)
```

Zero ceilings return `0.0` without calling `random.uniform`.

- [ ] **Step 5: Add response delay selection**

Use a valid bounded `Retry-After` exactly. Return `None` when it exceeds the configured maximum. Use fallback for missing or malformed values.

- [ ] **Step 6: Convert `_request()` into a finite loop**

Retry only when `method.lower() == "get"`. Exit each response context before sleeping. Keep the final typed transport error metadata unchanged.

- [ ] **Step 7: Verify focused and full gates**

```bash
uv sync --locked
uv run pytest -q tests/test_idempotent_get_retries.py tests/test_http_transport.py
uv run pytest -q -m "not integration"
uv run python -m compileall -q pg_llm_batch
uv run ruff check pg_llm_batch tests
uvx --from 'interrogate==1.7.0' interrogate --fail-under 100 pg_llm_batch
uv run --with pytest-cov==7.1.0 pytest -q -m "not integration" \
  --cov=pg_llm_batch --cov-report=term-missing --cov-fail-under=100
uv build --no-sources
```

Expected: every command exits zero and production statement and branch coverage remain 100%.

### Task 3: Document the retry boundary

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-04-idempotent-get-retries-design.md`

**Interfaces:**
- Consumes: the implemented constructor and retry behavior.
- Produces: operator examples, standards traceability, and release history.

- [ ] **Step 1: Document defaults and safe-method scope**

Show constructor overrides and state explicitly that POST operations are not retried.

- [ ] **Step 2: Document Retry-After handling**

Explain decimal seconds, HTTP-date, malformed fallback, and the maximum-delay refusal boundary.

- [ ] **Step 3: Update `CHANGELOG.md`**

Record bounded idempotent GET retries under `Unreleased / Added`.

### Task 4: Review, verify, and merge

**Files:**
- No new paths.

**Interfaces:**
- Consumes: exact-head human/automated reviews, CI, SAST, Security Scan, and repository policy.
- Produces: a merged reviewed head or a precise blocker.

- [ ] **Step 1: Address all valid current-head feedback**

Inspect human, CodeRabbit, GitHub security, and automated comments and threads. Resolve only addressed threads.

- [ ] **Step 2: Require exact-head gates**

Require successful CI, SAST Semgrep, Security Scan, package/container checks, Python compatibility, coverage, and docstrings. Pending or cancelled is not success.

- [ ] **Step 3: Merge with exact head binding**

Use a repository-supported merge method only after policy is satisfied.

- [ ] **Step 4: Re-query open PRs and continue**

Return the queue to zero whenever safely possible, then select the next buyer-visible product gap.