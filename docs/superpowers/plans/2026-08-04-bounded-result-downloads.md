# Bounded Result Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent provider result and error downloads from consuming unbounded process memory while preserving the disk-free Batch API contract.

**Architecture:** Add a validated decoded-byte limit to `BatchAPIClient` and route all provider file bodies through a single chunked UTF-8 reader. Use `Content-Length` only as an early rejection signal, then enforce the limit again against the actual bytes yielded by aiohttp after automatic decompression.

**Tech Stack:** Python 3.10+, asyncio, aiohttp `StreamReader.iter_chunked`, pytest, pytest-asyncio, pytest-cov, Ruff, Interrogate.

## Global Constraints

- Default maximum downloaded body size is exactly `128 * 1024 * 1024` bytes.
- Stream chunk size is exactly `64 * 1024` bytes.
- The limit counts decoded bytes yielded by aiohttp, not only `Content-Length`.
- Invalid values include booleans, non-integers, zero, and negative integers.
- Provider response content must never appear in oversize or invalid-UTF-8 error metadata.
- Existing disk-free behavior remains unchanged.
- Added production code must retain 100% statement, branch, and docstring coverage.
- Python 3.10, 3.12, and 3.14 remain supported.

---

### Task 1: Define the bounded-download contract

**Files:**
- Create: `tests/test_bounded_result_downloads.py`

**Interfaces:**
- Consumes: `BatchAPIClient`, `GatewayCredentials`, `GatewayError`, and `ValidationError`.
- Produces: failing behavioral tests for `max_download_bytes` and `_read_bounded_utf8()` integration through `_download_jsonl_file()`.

- [ ] **Step 1: Add a streamed response double**

```python
class ChunkStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.requested_sizes: list[int] = []
        self.iterated = False

    async def iter_chunked(self, size: int):
        self.requested_sizes.append(size)
        self.iterated = True
        for chunk in self.chunks:
            yield chunk
```

Add response/session doubles that expose `content_length`, `content`, `status`, asynchronous context-manager methods, and a `get()` route.

- [ ] **Step 2: Write failing validation tests**

```python
@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "1024"])
def test_client_rejects_invalid_max_download_bytes(value):
    with pytest.raises(ValidationError, match="max_download_bytes"):
        BatchAPIClient("postgresql://x", credentials, max_download_bytes=value)
```

- [ ] **Step 3: Write failing stream-limit tests**

Cover these exact cases:

```python
# declared Content-Length is over the limit and the stream is not iterated
# actual streamed bytes exceed a smaller declared length
# a body exactly equal to the limit parses successfully
# invalid UTF-8 raises GatewayError without body bytes
# a response double without `content` remains bounded through text()
```

Assert `limit_bytes`, `declared_bytes`, and `bytes_read` values in structured error metadata.

- [ ] **Step 4: Push the red tests and open a draft PR**

Expected current-head CI outcome: focused/new tests fail because `BatchAPIClient` does not accept `max_download_bytes` and does not enforce bounded streaming.

### Task 2: Implement bounded UTF-8 reads

**Files:**
- Modify: `pg_llm_batch/batch_api_client.py`
- Test: `tests/test_bounded_result_downloads.py`

**Interfaces:**
- Consumes: aiohttp response-like objects.
- Produces: `DEFAULT_MAX_DOWNLOAD_BYTES`, `DOWNLOAD_CHUNK_BYTES`, validated `self.max_download_bytes`, and `BatchAPIClient._read_bounded_utf8(response, operation) -> str`.

- [ ] **Step 1: Add constants**

```python
DEFAULT_MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
```

- [ ] **Step 2: Validate constructor input**

Reject values unless `isinstance(value, int)`, `not isinstance(value, bool)`, and `value > 0`. Raise:

```python
ValidationError(
    field="max_download_bytes",
    value=value,
    reason="must be a positive integer number of bytes",
)
```

- [ ] **Step 3: Add a structured oversize error helper**

Create a private method that raises `GatewayError` with status code, `limit_bytes`, `declared_bytes`, and `bytes_read`. Do not include chunks or decoded text.

- [ ] **Step 4: Implement `_read_bounded_utf8()`**

Algorithm:

```python
declared = getattr(response, "content_length", None)
if isinstance(declared, int) and declared > self.max_download_bytes:
    raise_oversize(bytes_read=0, declared_bytes=declared)

stream = getattr(response, "content", None)
if stream is None:
    text = await response.text()
    encoded = text.encode("utf-8")
    if len(encoded) > self.max_download_bytes:
        raise_oversize(bytes_read=0, declared_bytes=declared)
    return text

payload = bytearray()
async for chunk in stream.iter_chunked(DOWNLOAD_CHUNK_BYTES):
    if len(payload) + len(chunk) > self.max_download_bytes:
        raise_oversize(bytes_read=len(payload), declared_bytes=declared)
    payload.extend(chunk)
try:
    return payload.decode("utf-8")
except UnicodeDecodeError as exc:
    raise GatewayError(
        f"{operation} returned invalid UTF-8",
        status_code=getattr(response, "status", None),
        response_data={"error_type": type(exc).__name__, "byte_offset": exc.start},
    ) from exc
```

- [ ] **Step 5: Route both success and error bodies through the helper**

Replace direct `response.text()` calls in `_download_jsonl_file()` with `_read_bounded_utf8()`. Preserve existing JSONL parsing and HTTP-status behavior.

- [ ] **Step 6: Verify focused and full gates**

Run:

```bash
uv sync --locked
uv run pytest -q tests/test_bounded_result_downloads.py
uv run pytest -q -m "not integration"
uv run ruff check pg_llm_batch tests
uvx --from 'interrogate==1.7.0' interrogate --fail-under 100 pg_llm_batch
uv run --with pytest-cov==7.1.0 pytest -q -m "not integration" \
  --cov=pg_llm_batch --cov-report=term-missing --cov-fail-under=100
uv build --no-sources
```

Expected: all commands exit zero, with production line and branch coverage at 100%.

### Task 3: Document the operator contract

**Files:**
- Modify: `README.md`
- Create: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-04-bounded-result-downloads-design.md`

**Interfaces:**
- Consumes: the implemented constructor and error contract.
- Produces: an operator-visible safety default, override example, and release history entry.

- [ ] **Step 1: Document the constructor option**

Add an example:

```python
client = BatchAPIClient(
    dsn,
    config_credentials_provider(config, secrets),
    max_download_bytes=256 * 1024 * 1024,
)
```

State that the default is 128 MiB, the limit applies after aiohttp decompression, and oversize bodies fail before JSONL parsing.

- [ ] **Step 2: Add a Keep-a-Changelog-compatible file**

Create `CHANGELOG.md` with `Unreleased / Added` describing bounded streamed result and error downloads, and an `0.1.0` initial-release section dated `2026-07-12` based on the repository's initial extraction commit.

- [ ] **Step 3: Self-review documentation**

Confirm there are no placeholders, contradictory limits, or claims that hosted checks passed before they actually did.

### Task 4: Review, revalidate, and merge

**Files:**
- No new paths.

**Interfaces:**
- Consumes: the exact PR head, review threads, CodeRabbit status, CI, SAST, and Security Scan.
- Produces: either a safely merged PR or a precise unresolved blocker.

- [ ] **Step 1: Inspect every current-head review source**

Review human submissions, inline threads, CodeRabbit, GitHub security feedback, and top-level comments. Fix only valid current-head findings.

- [ ] **Step 2: Inspect exact-head workflow results**

Require successful `CI`, `SAST Semgrep`, and `Security Scan`; never treat queued, pending, skipped unexpectedly, or cancelled runs as success.

- [ ] **Step 3: Merge with head binding**

Merge only with the exact reviewed head SHA and a repository-supported merge method.

- [ ] **Step 4: Re-query the queue**

Confirm the open PR count returns to zero, then continue to the next highest-impact buyer-visible gap.