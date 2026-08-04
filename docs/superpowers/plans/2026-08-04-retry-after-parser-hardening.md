# Hostile Retry-After Parser Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make untrusted `Retry-After` delta parsing RFC-correct and exception-safe without changing the public retry API.

**Architecture:** Tighten the existing pure `_parse_retry_after()` boundary to accept only ASCII decimal digits and convert them directly to floating point. Reuse the existing maximum-delay policy to refuse infinite or excessive guidance, while preserving HTTP-date handling and GET-only retry behavior.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, `email.utils`, pytest, pytest-asyncio, pytest-cov, Ruff, Interrogate.

## Global Constraints

- `delay-seconds` accepts ASCII decimal digits only.
- A 5,000-digit ASCII delta returns positive infinity instead of raising.
- Non-ASCII decimal digits are malformed guidance and use fallback behavior.
- Excessive valid guidance disables that retry rather than being shortened.
- POST operations remain single-attempt.
- Existing public constructor and error shapes remain compatible.
- Production statement, branch, and docstring coverage remain 100%.
- Python 3.10, 3.12, and 3.14 remain supported.

---

### Task 1: Define the hostile-header regression contract

**Files:**
- Create: `tests/test_retry_after_parser_hardening.py`
- Test: `pg_llm_batch/batch_api_client.py`

**Interfaces:**
- Consumes: `pg_llm_batch.batch_api_client._parse_retry_after(value, now)`.
- Produces: focused failing tests for oversized ASCII and non-ASCII decimal values.

- [x] **Step 1: Write the focused failing tests**

```python
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for hostile and non-standard Retry-After values."""

from __future__ import annotations

from datetime import datetime, timezone

from pg_llm_batch import batch_api_client as client_mod


def test_oversized_ascii_delta_is_classified_as_excessive() -> None:
    """A huge ASCII delta must not hit Python's bounded-int conversion error."""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert client_mod._parse_retry_after("9" * 5000, now) == float("inf")


def test_non_ascii_decimal_digits_are_not_rfc_delta_seconds() -> None:
    """RFC delay-seconds use ASCII DIGIT, not arbitrary Unicode decimals."""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert client_mod._parse_retry_after("１２", now) is None
```

- [x] **Step 2: Run the focused tests and require a red result**

Run:

```bash
uv sync --locked
uv run pytest -q tests/test_retry_after_parser_hardening.py
```

Expected: failure because the oversized value raises `ValueError` and fullwidth digits are currently accepted.

- [x] **Step 3: Preserve red evidence**

Record the failing command, exact pre-fix head, and failure reason in the PR description or a committed evidence note. Do not reinterpret an unrelated setup failure as TDD evidence.

### Task 2: Apply the minimal RFC-aligned parser fix

**Files:**
- Modify: `pg_llm_batch/batch_api_client.py`
- Test: `tests/test_retry_after_parser_hardening.py`
- Test: `tests/test_idempotent_get_retries.py`
- Test: `tests/test_retry_edge_coverage.py`

**Interfaces:**
- Consumes: stripped candidate header strings.
- Produces: `_parse_retry_after(value: Any, now: datetime) -> Optional[float]` with ASCII-only decimal handling.

- [x] **Step 1: Replace the decimal branch**

```python
if candidate.isascii() and candidate.isdecimal():
    return float(candidate)
```

Do not add a second retry limit or alter HTTP-date parsing.

- [x] **Step 2: Run the focused tests**

Run:

```bash
uv run pytest -q tests/test_retry_after_parser_hardening.py
```

Expected: `2 passed`.

- [x] **Step 3: Run the complete retry boundary suite**

Run:

```bash
uv run pytest -q \
  tests/test_retry_after_parser_hardening.py \
  tests/test_idempotent_get_retries.py \
  tests/test_retry_edge_coverage.py \
  tests/test_http_transport.py
```

Expected: every test passes; excessive guidance still causes no retry sleep or replay.

### Task 3: Align operator and release documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-04-retry-after-parser-hardening-design.md`

**Interfaces:**
- Consumes: the implemented parser contract.
- Produces: explicit wire grammar and release-history traceability.

- [x] **Step 1: Clarify README grammar**

Change:

```text
A bounded RFC `Retry-After` delta or HTTP-date is honored;
```

to:

```text
A bounded RFC `Retry-After` ASCII delta or HTTP-date is honored;
```

- [x] **Step 2: Add the changelog entry**

Under `Unreleased`, add:

```markdown
### Fixed

- Retry-After parsing now rejects non-ASCII decimal digits and treats oversized
  ASCII deltas as excessive guidance without triggering Python integer-conversion
  limits.
```

- [x] **Step 3: Self-review documentation**

Confirm there are no placeholders, no claim that exact-head hosted checks have already passed, and no contradiction with the maximum-delay refusal policy.

### Task 4: Verify, review, and merge

**Files:**
- No new production paths.

**Interfaces:**
- Consumes: exact feature head, review feedback, CI, SAST Semgrep, and Security Scan.
- Produces: a safely merged hardening change or a precise external blocker.

- [ ] **Step 1: Run all local-quality gates**

```bash
uv run pytest -q -m "not integration"
uv run python -m compileall -q pg_llm_batch
uv run ruff check pg_llm_batch tests
uvx --from 'interrogate==1.7.0' interrogate --fail-under 100 pg_llm_batch
uv run --with pytest-cov==7.1.0 pytest -q -m "not integration" \
  --cov=pg_llm_batch --cov-report=term-missing --cov-fail-under=100
uv lock --check
uv build --no-sources
```

Expected: all commands exit zero and production statement/branch/docstring coverage is 100%.

- [ ] **Step 2: Inspect every current-head review source**

Require no unresolved human, CodeRabbit, or security findings. Address valid comments in code and re-run the full gate set.

- [ ] **Step 3: Require exact-head hosted checks**

Require `CI`, `SAST Semgrep`, and `Security Scan` to complete successfully. Queued, pending, cancelled, action-required, or unexpectedly skipped results are not success.

- [ ] **Step 4: Merge with exact-head binding**

Use a repository-supported merge method and the reviewed head SHA. Then re-query the open PR queue before selecting another product gap.
