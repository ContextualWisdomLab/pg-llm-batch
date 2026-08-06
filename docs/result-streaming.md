# Bounded result streaming

`StreamingBatchAPIClient` is the opt-in retrieval boundary for batches whose
provider output may be too large to materialize safely as one string and one
Python list. The original `BatchAPIClient.download_results()` remains source
compatible for callers that explicitly want an in-memory aggregate.

## Usage

```python
from pg_llm_batch import StreamingBatchAPIClient

async with StreamingBatchAPIClient(
    dsn,
    credentials_provider,
    max_download_bytes=128 * 1024 * 1024,
    max_jsonl_line_bytes=1 * 1024 * 1024,
    max_jsonl_records=100_000,
) as client:
    async for item in client.iter_batch_records("batch-123", "default"):
        persist(item.file_kind, item.record)
```

Records are emitted in deterministic provider-file order: all output records,
then all error records. A failed batch that exposes only an error file is valid.
An incomplete batch or terminal batch with neither file identifier fails closed.

## Resource and trust boundaries

- The inherited total decoded-byte limit is enforced independently for each
  provider file from both declared and observed bytes.
- `max_jsonl_line_bytes` caps one physical line before UTF-8 decoding or JSON
  parsing, including a final line without a newline.
- `max_jsonl_records` caps the combined output-plus-error record count for one
  iterator.
- Response data is consumed only through `content.iter_chunked(64 KiB)`. An
  adapter that omits the interface, emits a non-byte chunk, or yields a chunk
  larger than the requested 64 KiB fails closed before package-owned line
  buffering.
- Redirects remain disabled, provider identifiers remain validated before URL
  construction, and only idempotent GET transport operations use bounded retry.
- Every nonblank line must be strict UTF-8 and decode to one interoperable JSON
  object. Arrays, scalars, non-finite number extensions, duplicate object names,
  malformed JSON, and invalid UTF-8 are rejected with body-free diagnostics.
- Parser diagnostics exclude provider batch and file identifiers as well as
  record content.
- Non-success file responses are rejected before reading the provider-controlled
  body.

The iterator bounds library-owned buffering, not downstream consumer behavior.
A caller that appends every yielded record to a list recreates aggregate memory
use and must size its own process accordingly. Cancellation and early loop exit
close the active response context through normal asynchronous-generator cleanup.

## Compatibility and observability

The streaming client subclasses `BatchAPIClient`, so credentials, gateway URL
validation, timeouts, retry policy, and session lifecycle remain identical. It
does not require PostgreSQL schema changes or another CWL service. Embedding hosts
may consume each record into their own durable queue, tenant-qualified store, or
bounded transformation pipeline.

The existing OpenTelemetry subclass does not automatically wrap this opt-in
iterator. Hosts that need per-record pipeline telemetry should instrument the
consumer boundary with low-cardinality attributes and must not attach provider
identifiers, prompts, response bodies, or model output.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format*
(RFC 8259; STD 90). Internet Engineering Task Force.
https://doi.org/10.17487/RFC8259

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646* (RFC 3629;
STD 63). Internet Engineering Task Force. https://doi.org/10.17487/RFC3629

aiohttp contributors. (2026). *Streaming API: StreamReader.iter_chunked*.
https://docs.aiohttp.org/en/stable/streams.html
