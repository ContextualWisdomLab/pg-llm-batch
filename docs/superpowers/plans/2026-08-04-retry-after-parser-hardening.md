# Retry-After Parser Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make provider-controlled `Retry-After` delta-seconds RFC-conformant and resistant to hostile Unicode and extremely long numeric values without changing retry policy.

**Architecture:** Keep parsing in `_parse_retry_after(value, now)` and policy enforcement in `_retry_delay_for_response(response, failed_attempt)`. Accept only ASCII digits for delta-seconds, parse them directly as `float`, and let the existing configured maximum refuse excessive or infinite guidance.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, pytest, pytest-asyncio, pytest-cov, Ruff, Interrogate, GitHub Actions.

## Global Constraints

- RFC 9110 delta-seconds accept only ASCII `0` through `9`.
- Provider-controlled numeric length must not raise raw `ValueError` or `OverflowError`.
- Guidance above `retry_max_delay_seconds` is refused rather than truncated.
- Malformed guidance continues to use bounded equal-jitter fallback.
- `POST` operations remain single-attempt.
- Existing status codes, attempt counts, delay defaults, HTTP-date behavior, and final error contracts remain unchanged.
- Production statement, branch, and docstring coverage remain 100%.
- Python 3.10, 3.12, and 3.14 remain supported.

---

### Task 1: Prove the hostile-header regression

**Files:**
- Modify: `tests/test_idempotent_get_retries.py`
- Create temporarily: `.github/workflows/one-shot-retry-after-red.yml`
- Create after execution: `docs/superpowers/evidence/2026-08-04-retry-after-parser-red.md`

**Interfaces:**
- Consumes: `batch_api_client._parse_retry_after(value: Any, now: datetime) -> Optional[float]`, `BatchAPIClient.get_batch_status()`.
- Produces: failing tests that distinguish the current Unicode/`int()` parser from the required ASCII/direct-float parser.

- [ ] **Step 1: Add a parser regression for Unicode decimal characters**

Add this test beside the existing malformed-value parser test:

```python
@pytest.mark.parametrize("value", ["٠", "１２", "２"])
def test_retry_after_parser_rejects_non_ascii_decimal_digits(value: str) -> None:
    """HTTP delay-seconds accept RFC ASCII DIGIT tokens only."""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert client_mod._parse_retry_after(value, now) is None
```

This fails on the existing `isdecimal()` implementation because those strings are accepted as numeric delay values.

- [ ] **Step 2: Add an end-to-end regression for hostile numeric length**

Add this test:

```python
async def test_extreme_ascii_retry_after_is_refused_without_exception(
    monkeypatch,
) -> None:
    """An extreme RFC-valid delay cannot escape or force a provider-selected wait."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    response = Response(
        429,
        {"error": "rate-limited"},
        headers={"Retry-After": "9" * 10_000},
    )
    session = SequenceSession([response])
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        retry_max_delay_seconds=30,
    )
    client._session = session

    with pytest.raises(GatewayError, match="Batch status failed") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.status_code == 429
    assert response.exit_count == 1
    assert sleeps == []
    assert len(session.calls) == 1
```

The existing implementation fails by leaking Python's decimal integer conversion `ValueError` before returning the provider `GatewayError`.

- [ ] **Step 3: Add an end-to-end fallback test for Unicode decimal guidance**

Add this test:

```python
async def test_non_ascii_retry_after_uses_bounded_fallback(monkeypatch) -> None:
    """Non-RFC decimal lookalikes select bounded fallback rather than exact delay."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    session = SequenceSession(
        [
            Response(503, {"error": "busy"}, headers={"Retry-After": "２"}),
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    result = await client.get_batch_status("batch-1", "default")

    assert result["status"] == "completed"
    assert sleeps == [0.5]
    assert len(session.calls) == 2
```

The existing parser sleeps exactly two seconds instead of selecting bounded jitter.

- [ ] **Step 4: Run the focused tests and capture the expected red evidence**

Run:

```bash
uv sync --locked
set +e
uv run pytest -q \
  tests/test_idempotent_get_retries.py::test_retry_after_parser_rejects_non_ascii_decimal_digits \
  tests/test_idempotent_get_retries.py::test_extreme_ascii_retry_after_is_refused_without_exception \
  tests/test_idempotent_get_retries.py::test_non_ascii_retry_after_uses_bounded_fallback \
  > /tmp/retry-after-red.log 2>&1
status=$?
set -e
cat /tmp/retry-after-red.log
if [ "$status" -eq 0 ]; then
  echo "Expected focused Retry-After regressions to fail before implementation" >&2
  exit 1
fi
grep -Eq 'ValueError|assert .* is None|assert \[2\.0\] == \[0\.5\]' /tmp/retry-after-red.log
```

Expected: the workflow succeeds only because the focused tests fail for the intended parser defects.

- [ ] **Step 5: Record red evidence and remove the temporary workflow**

Write `docs/superpowers/evidence/2026-08-04-retry-after-parser-red.md` with the pre-implementation head SHA, command, non-zero exit status, and the observed failure classes. Delete the temporary workflow in the same commit.

- [ ] **Step 6: Commit the red contract**

```bash
git add tests/test_idempotent_get_retries.py \
  docs/superpowers/evidence/2026-08-04-retry-after-parser-red.md \
  .github/workflows/one-shot-retry-after-red.yml
git commit -m "test(gateway): define hostile Retry-After boundary"
```

### Task 2: Implement the RFC-conformant parser

**Files:**
- Modify: `pg_llm_batch/batch_api_client.py`
- Test: `tests/test_idempotent_get_retries.py`

**Interfaces:**
- Consumes: provider header value and timezone-aware `now`.
- Produces: `_parse_retry_after(value: Any, now: datetime) -> Optional[float]` with ASCII-only delta-seconds and length-safe conversion.

- [ ] **Step 1: Replace Unicode decimal detection and `int()` conversion**

Change:

```python
if candidate.isdecimal():
    return float(int(candidate))
```

To:

```python
if candidate.isascii() and candidate.isdigit():
    return float(candidate)
```

This is the only production behavior change.

- [ ] **Step 2: Run the focused retry tests**

Run:

```bash
uv run pytest -q tests/test_idempotent_get_retries.py
```

Expected: all tests in the module pass, including the three new regressions.

- [ ] **Step 3: Run the complete non-integration suite**

Run:

```bash
uv run pytest -q -m "not integration"
```

Expected: all tests pass with three integration tests deselected.

- [ ] **Step 4: Commit the minimal production change**

```bash
git add pg_llm_batch/batch_api_client.py tests/test_idempotent_get_retries.py
git commit -m "fix(gateway): harden Retry-After delta parsing"
```

### Task 3: Document the external contract

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-04-retry-after-parser-hardening-design.md`

**Interfaces:**
- Consumes: the implemented parser behavior.
- Produces: operator-visible RFC grammar and release history.

- [ ] **Step 1: Clarify README retry guidance**

Update the retry paragraph to state:

```text
Retry-After delta-seconds accept the RFC ASCII digit grammar only. Syntactically
valid values above the configured maximum are refused; malformed values use the
bounded fallback policy.
```

- [ ] **Step 2: Record the fix in CHANGELOG**

Add:

```markdown
### Fixed

- Hardened provider `Retry-After` delta parsing to accept RFC ASCII digits only
  and refuse extremely long numeric guidance without leaking Python integer
  conversion errors.
```

- [ ] **Step 3: Align the implementation plan status**

Mark Tasks 1–3 completed only after their exact commands have passed. Do not mark hosted review or checks complete before GitHub reports success.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md CHANGELOG.md \
  docs/superpowers/specs/2026-08-04-retry-after-parser-hardening-design.md \
  docs/superpowers/plans/2026-08-04-retry-after-parser-hardening.md
git commit -m "docs: specify hardened Retry-After parsing"
```

### Task 4: Verify, review, and merge

**Files:**
- No new production paths.

**Interfaces:**
- Consumes: exact PR head, repository workflows, CodeRabbit status, review submissions, comments, and threads.
- Produces: a safely merged PR or an explicit external blocker.

- [ ] **Step 1: Run local-equivalent quality gates**

```bash
uv sync --locked
uv run python -m compileall -q pg_llm_batch
uv run ruff check pg_llm_batch tests
uvx --from 'interrogate==1.7.0' interrogate --fail-under 100 pg_llm_batch
uv run --with pytest-cov==7.1.0 pytest -q -m "not integration" \
  --cov=pg_llm_batch --cov-report=term-missing --cov-fail-under=100
uv lock --check
uv build --no-sources
docker compose config >/dev/null
docker build --tag pg-llm-batch:retry-after .
docker build --tag pg-llm-batch-postgres:retry-after docker/postgres
```

Expected: every command exits zero; production statements, branches, and docstrings remain 100%.

- [ ] **Step 2: Open or update the PR with exact evidence**

The PR body must include the red head, final head, focused/full test counts, coverage totals, build results, RFC 9110 basis, and release decision.

- [ ] **Step 3: Inspect every review source on the final head**

Require no actionable human, CodeRabbit, security, or inline review findings. Resolve only threads whose findings are actually addressed.

- [ ] **Step 4: Require exact-head hosted gates**

Require successful `CI`, `SAST Semgrep`, and `Security Scan`. Pending, queued, action-required, cancelled, or unexpectedly skipped outcomes are not success.

- [ ] **Step 5: Merge with head binding and re-query the queue**

Merge using the repository-supported method with the reviewed head SHA. Confirm the open PR count returns to zero before selecting the next buyer-visible gap.
