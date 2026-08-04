# Bounded Result Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent provider result and error downloads from consuming unbounded process memory while preserving the disk-free Batch API contract.

**Architecture:** Add a validated decoded-byte limit to `BatchAPIClient` and route every provider file body through one chunked UTF-8 reader. Use `Content-Length` only as an early rejection signal, enforce the limit against the actual bytes yielded by aiohttp after automatic decompression, and fail closed when an adapter cannot expose a bounded byte stream.

**Tech Stack:** Python 3.10+, asyncio, aiohttp `StreamReader.iter_chunked`, pytest, pytest-asyncio, pytest-cov, Ruff, Interrogate.

## Global Constraints

- Default maximum downloaded body size is exactly `128 * 1024 * 1024` bytes.
- Stream chunk size is exactly `64 * 1024` bytes.
- The limit counts decoded bytes yielded by aiohttp, not only `Content-Length`.
- Invalid values include booleans, non-integers, zero, and negative integers.
- Provider response content must never appear in oversize or invalid-UTF-8 error metadata.
- Responses without a callable `content.iter_chunked` stream fail closed; `response.text()` is never used for provider file bodies.
- Existing disk-free behavior remains unchanged.
- Added production code must retain 100% statement, branch, and docstring coverage.
- Python 3.10, 3.12, and 3.14 remain supported.

---

### Task 1: Define the bounded-download contract

**Files:**
- Create: `tests/test_bounded_result_downloads.py`
- Modify: `tests/test_batch_api_client.py`
- Modify: `tests/test_error_file_retrieval.py`

**Interfaces:**
- Consumes: `BatchAPIClient`, `GatewayCredentials`, `GatewayError`, and `ValidationError`.
- Produces: behavioral tests for `max_download_bytes`, `_read_bounded_utf8()`, and bounded response doubles used by existing retrieval tests.

- [x] **Step 1: Add a streamed response double**

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

- [x] **Step 2: Define constructor validation**

```python
@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "1024"])
def test_client_rejects_invalid_max_download_bytes(value):
    with pytest.raises(ValidationError, match="max_download_bytes"):
        BatchAPIClient("postgresql://x", credentials, max_download_bytes=value)
```

- [x] **Step 3: Define stream and error boundary cases**

The focused suite covers:

```text
- declared Content-Length above the limit without stream consumption
- malformed declared lengths that cannot weaken actual-byte enforcement
- actual streamed bytes exceeding an understated declared length
- a body exactly equal to the limit
- strict UTF-8 rejection without response-content leakage
- a response without content.iter_chunked failing before text() is called
```

- [x] **Step 4: Update existing response doubles**

`FakeResponse` and the provider error-file `Response` expose deterministic byte streams so existing download tests exercise the production contract rather than a whole-body fallback.

### Task 2: Implement bounded UTF-8 reads

**Files:**
- Modify: `pg_llm_batch/batch_api_client.py`
- Test: `tests/test_bounded_result_downloads.py`

**Interfaces:**
- Consumes: aiohttp response-like objects with `status`, `content_length`, and callable `content.iter_chunked`.
- Produces: `DEFAULT_MAX_DOWNLOAD_BYTES`, `DOWNLOAD_CHUNK_BYTES`, validated `self.max_download_bytes`, and `BatchAPIClient._read_bounded_utf8(response, operation) -> str`.

- [x] **Step 1: Add constants**

```python
DEFAULT_MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
```

- [x] **Step 2: Validate constructor input**

Reject values unless `isinstance(value, int)`, `not isinstance(value, bool)`, and `value > 0`.

- [x] **Step 3: Add a body-free oversize error helper**

The helper records only status, `limit_bytes`, `declared_bytes`, and `bytes_read`.

- [x] **Step 4: Implement `_read_bounded_utf8()`**

```python
declared_value = getattr(response, "content_length", None)
declared_bytes = (
    declared_value
    if isinstance(declared_value, int)
    and not isinstance(declared_value, bool)
    and declared_value >= 0
    else None
)
if declared_bytes is not None and declared_bytes > self.max_download_bytes:
    raise self._download_limit_error(
        response,
        operation,
        declared_bytes=declared_bytes,
        bytes_read=0,
    )

stream = getattr(response, "content", None)
iterator = getattr(stream, "iter_chunked", None)
if not callable(iterator):
    raise GatewayError(
        f"{operation} response does not expose a bounded byte stream",
        status_code=getattr(response, "status", None),
        response_data={"error_type": "MissingBoundedStream"},
    )

payload = bytearray()
async for chunk in iterator(DOWNLOAD_CHUNK_BYTES):
    if len(payload) + len(chunk) > self.max_download_bytes:
        raise self._download_limit_error(
            response,
            operation,
            declared_bytes=declared_bytes,
            bytes_read=len(payload),
        )
    payload.extend(chunk)
```

Decode the complete bounded bytearray as strict UTF-8 and report only the exception type and byte offset on failure.

- [x] **Step 5: Route success and error bodies through the helper**

`_download_jsonl_file()` no longer calls `response.text()` for provider file bodies.

- [ ] **Step 6: Verify the final hardened head**

Run on the exact final head:

```bash
uv sync --locked
uv run pytest -q tests/test_bounded_result_downloads.py
uv run pytest -q -m "not integration"
uv run python -m compileall -q pg_llm_batch
uv run ruff check pg_llm_batch tests
uvx --from 'interrogate==1.7.0' interrogate --fail-under 100 pg_llm_batch
uv run --with pytest-cov==7.1.0 pytest -q -m "not integration" \
  --cov=pg_llm_batch --cov-report=term-missing --cov-fail-under=100
uv build --no-sources
```

Expected: every command exits zero, with production statement and branch coverage at 100%.

### Task 3: Document the operator contract

**Files:**
- Modify: `README.md`
- Create: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-08-04-bounded-result-downloads-design.md`

**Interfaces:**
- Consumes: the implemented constructor, bounded stream requirement, and error contract.
- Produces: an operator-visible safety default, override example, and release history entry.

- [x] **Step 1: Document the constructor option**

```python
client = BatchAPIClient(
    dsn,
    config_credentials_provider(config, secrets),
    max_download_bytes=256 * 1024 * 1024,
)
```

- [x] **Step 2: Add a Keep-a-Changelog-compatible file**

`CHANGELOG.md` contains `Unreleased / Added` and an `0.1.0` initial-release section dated `2026-07-12`.

- [x] **Step 3: Align documentation with fail-closed behavior**

Documentation must not claim that adapters without a bounded byte stream remain compatible.

### Task 4: Review, revalidate, and merge

**Files:**
- No new paths.

**Interfaces:**
- Consumes: the exact PR head, review threads, CodeRabbit status, CI, SAST, and Security Scan.
- Produces: either a safely merged PR or a precise unresolved blocker.

- [ ] **Step 1: Inspect every current-head review source**

Review human submissions, inline threads, CodeRabbit, GitHub security feedback, and top-level comments. Fix only valid current-head findings.

- [ ] **Step 2: Inspect exact-head workflow results**

Require successful `CI`, `SAST Semgrep`, and `Security Scan`; never treat queued, pending, unexpectedly skipped, or cancelled runs as success.

- [ ] **Step 3: Merge with head binding**

Merge only with the exact reviewed head SHA and a repository-supported merge method.

- [ ] **Step 4: Re-query the queue**

Confirm the open PR count returns to zero, then continue to the next highest-impact buyer-visible gap.