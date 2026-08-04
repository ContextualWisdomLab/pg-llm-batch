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
- Create: `tests/test_retry_edge_coverage.py`
- Modify: `tests/test_http_transport.py`

**Interfaces:**
- Consumes: `BatchAPIClient`, `GatewayCredentials`, `GatewayError`, and `ValidationError`.
- Produces: tests for retry configuration, RFC `Retry-After`, status retries, transport retries, final attempts, response-context release, and non-retried POST operations.

- [x] **Step 1: Add response and sequence session doubles**
- [x] **Step 2: Write constructor validation tests**
- [x] **Step 3: Write Retry-After parsing and delay tests**
- [x] **Step 4: Write GET status and transport retry tests**
- [x] **Step 5: Write POST non-retry tests**
- [x] **Step 6: Commit and execute the red contract**

The focused command failed on pre-implementation head `91077f0c58406542ab4b4f50f660babe499ef722` for the expected missing retry interface. The evidence is retained in `docs/superpowers/evidence/2026-08-04-idempotent-get-retries-red.md`.

### Task 2: Implement the bounded retry policy

**Files:**
- Modify: `pg_llm_batch/batch_api_client.py`
- Test: `tests/test_idempotent_get_retries.py`
- Test: `tests/test_retry_edge_coverage.py`
- Modify: `tests/test_http_transport.py`

**Interfaces:**
- Consumes: aiohttp response-like contexts and existing request operations.
- Produces: retry constants, constructor options, `_utc_now()`, `_parse_retry_after()`, `_normalize_retry_delay()`, `_fallback_retry_delay()`, `_retry_delay_for_response()`, and retry-aware `_request()`.

- [x] **Step 1: Add imports and constants**

```python
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DEFAULT_MAX_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5
DEFAULT_RETRY_MAX_DELAY_SECONDS = 30.0
RETRYABLE_GET_STATUSES = frozenset({408, 429, 502, 503, 504})
```

- [x] **Step 2: Add pure parsing and normalization helpers**
- [x] **Step 3: Validate constructor options**
- [x] **Step 4: Add bounded equal-jitter fallback**
- [x] **Step 5: Add response delay selection**
- [x] **Step 6: Convert `_request()` into a finite GET-only retry loop**
- [x] **Step 7: Verify focused and full gates before publishing the implementation commit**

Verification on Python 3.14.6 produced:

```text
45 focused retry/transport tests passed
228 non-integration tests passed; 3 integration tests deselected
Ruff: clean
Interrogate: 100%
Production statements: 1171/1171
Production branches: 324/324
Wheel and source distribution: built successfully
```

The temporary implementation workflow removed itself before committing the feature tree.

### Task 3: Document the retry boundary

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Create: `docs/superpowers/specs/2026-08-04-idempotent-get-retries-design.md`

**Interfaces:**
- Consumes: the implemented constructor and retry behavior.
- Produces: operator examples, standards traceability, and release history.

- [x] **Step 1: Document defaults and safe-method scope**
- [x] **Step 2: Document Retry-After handling and the excessive-delay refusal boundary**
- [x] **Step 3: Record bounded GET retries under `Unreleased / Added`**

### Task 4: Review, verify, and merge

**Files:**
- No new paths.

**Interfaces:**
- Consumes: the exact PR head, human and automated reviews, CI, SAST, Security Scan, and repository policy.
- Produces: a merged reviewed head or a precise unresolved blocker.

- [ ] **Step 1: Address all valid current-head feedback**

Inspect human, CodeRabbit, GitHub security, and automated comments and threads. Resolve only addressed threads.

- [ ] **Step 2: Require exact-head gates**

Require successful CI, SAST Semgrep, Security Scan, package/container checks, Python compatibility, coverage, and docstrings. Pending, action-required, skipped unexpectedly, or cancelled is not success.

- [ ] **Step 3: Merge with exact head binding**

Use a repository-supported merge method only after policy is satisfied.

- [ ] **Step 4: Re-query open PRs and continue**

Return the queue to zero whenever safely possible, then select the next buyer-visible product gap.