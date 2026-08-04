# Bounded Result Downloads Design

## Context

`BatchAPIClient._download_jsonl_file()` currently calls `response.text()`. In aiohttp, `ClientResponse.text()` reads the complete response body into memory. A large, malformed, or compressed provider response can therefore consume unbounded process memory before JSONL validation begins. This is a buyer-visible reliability and security gap for long-running batch workers.

Aiohttp exposes `ClientResponse.content` as a `StreamReader`; `iter_chunked(n)` yields bounded chunks and automatically reflects decoded response bytes when response decompression is enabled. `Content-Length` is useful for early rejection, but it cannot be the only control because it may be absent, inaccurate, or describe compressed wire bytes rather than decoded content.

## Selected approach

Add a configurable, fail-closed decoded-byte limit to `BatchAPIClient` and read result/error files through one bounded UTF-8 helper.

The client will:

1. reject invalid limits during construction;
2. reject a declared `Content-Length` above the limit before consuming the body;
3. stream `response.content.iter_chunked(64 KiB)` when an aiohttp stream is available;
4. count the actual decoded bytes yielded by the stream and stop as soon as the limit would be exceeded;
5. decode the completed bounded payload as strict UTF-8;
6. convert oversize and invalid-UTF-8 responses into structured `GatewayError` values without including response bytes;
7. retain a bounded `response.text()` compatibility path for lightweight response doubles and compatible adapters that do not expose `content`.

The default limit is 128 MiB. Callers may raise it with `max_download_bytes`, but zero, booleans, floats, strings, and negative values are rejected. The limit applies to both successful result files and error response bodies.

## Alternatives considered

### Keep `response.text()` and check length afterward

This preserves the smallest diff but does not prevent the memory spike. It only detects the problem after the body is already resident, so it does not close the gap.

### Parse JSONL directly from streamed lines

This minimizes duplicate raw-body memory and may be useful later, but it expands the change into incremental UTF-8 decoding, line-boundary state, object-count limits, and partial-result semantics. The current API returns full Python lists, so a bounded raw payload is the smallest reviewable safety improvement.

### Write provider output to disk

This conflicts with the package's disk-free operating model and creates cleanup, encryption, tenancy, and filesystem-permission concerns. It is not selected.

## Interfaces

`BatchAPIClient.__init__()` gains:

```python
max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
```

The client stores the validated integer as `self.max_download_bytes`.

A private helper is added:

```python
async def _read_bounded_utf8(self, response: Any, operation: str) -> str
```

It returns decoded text only when the entire body is within the configured limit and valid UTF-8.

## Error contract

Oversize responses raise `GatewayError` with:

```json
{
  "limit_bytes": 134217728,
  "declared_bytes": 200000000,
  "bytes_read": 0
}
```

`declared_bytes` is `null` when no usable length was supplied. Mid-stream failures report the bytes accepted before the rejected chunk. Invalid UTF-8 reports the error type and byte offset but never echoes provider content.

Transport framing and decompression errors remain typed by the existing `_request()` boundary because aiohttp raises `ClientPayloadError`, which is an `aiohttp.ClientError`.

## Testing

Focused tests cover:

- constructor validation;
- preflight rejection from `Content-Length` without iterating the stream;
- exact-limit success;
- streamed decoded bytes exceeding a smaller declared length;
- invalid UTF-8;
- the bounded compatibility path without `response.content`;
- structured error details without response-body leakage.

The repository CI must continue to prove Python 3.10, 3.12, and 3.14 compatibility, Ruff cleanliness, 100% line and branch coverage, 100% docstring coverage, package construction, and both container builds.

## Verification evidence

The implementation was exercised on Python 3.14.6 before the final feature head was created:

- 16 focused bounded-download tests passed;
- 194 non-integration tests passed and 3 integration tests were deselected;
- Ruff reported no findings;
- Interrogate reported 100% docstring coverage;
- all 1,105 production statements and all 300 measured branches were covered;
- source and wheel distributions built successfully with `uv build --no-sources`.

These results are implementation evidence, not a substitute for the required exact-head CI, SAST, Security Scan, and review gates.

## Documentation and release handling

README documents the safety default and override. `CHANGELOG.md` records the feature under `Unreleased`. This slice does not publish a release by itself; release publication remains gated on the integrated exact head passing all review, CI, security, packaging, provenance, and release-acceptance requirements.