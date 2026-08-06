# Doctoring: bounded JSONL result streaming

## Decision and assurance scope

This doctoring record supports ADR 0005 and the opt-in
`StreamingBatchAPIClient`. It documents the claim that library-owned retrieval
memory is bounded independently of a provider file's permitted total size. The
claim is limited to the package-owned HTTP and JSONL parsing path; downstream
queues, persistence adapters, transformations, and callers remain separate trust
and resource boundaries.

The aggregate `BatchAPIClient.download_results()` API is intentionally retained
for source compatibility. It is not represented as a constant-memory interface.

## Assets and threat model

Protected assets are process availability, tenant workload isolation, provider
credentials, result confidentiality, deterministic reconciliation, and the
integrity of records admitted to downstream processing.

Provider-controlled or adapter-controlled inputs include HTTP status, declared
content length, decoded byte chunks, JSONL line boundaries, UTF-8 sequences, JSON
nesting and types, file identifiers, record counts, and error bodies. Relevant
failure modes include:

- a policy-compliant file expanding into an unbounded decoded string and Python
  object list;
- a newline-free record growing without a line-level cap;
- chunk boundaries splitting UTF-8 code units or JSON tokens;
- missing, false, negative, or encoded-length metadata misleading a byte budget;
- non-byte adapter chunks bypassing byte accounting;
- malformed UTF-8, JSON arrays or scalars, or recursively pathological JSON
  entering durable workflows;
- redirect-based destination changes or unsafe provider identifiers altering the
  request boundary;
- non-success response bodies being read into memory or leaked through errors;
- result and error files jointly exceeding a host's expected record budget; and
- a caller collecting every yielded record and recreating aggregate memory use.

## Normative resource contract

| Boundary | Default | Enforcement point | Failure behavior |
| --- | ---: | --- | --- |
| Control-plane JSON response | 1 MiB | inherited bounded status reader | fail closed before object acceptance |
| One provider result or error file | 128 MiB decoded bytes | declared and observed byte accounting | fail closed with body-free byte counts |
| One physical JSONL line | 1 MiB | before UTF-8 decoding and JSON parsing | fail closed with line number and bounded counts |
| One batch iterator | 100,000 objects | before yielding the first excessive record | fail closed with count and configured limit |
| HTTP stream chunk request | 64 KiB | `iter_chunked` adapter contract | reject adapters without bounded byte streaming |

Each provider file receives an independent total-download budget. The record
budget is combined across the deterministic output-then-error sequence. Blank
physical lines do not consume the record budget. Limits are strict positive
integers; booleans and coercible strings are rejected rather than normalized.

The implementation may temporarily hold one transport chunk, one bounded line,
one decoded text value, and one decoded JSON object. Python allocator behavior,
JSON object expansion, and a caller's retained references prevent a claim of an
exact resident-set-size ceiling. The defensible claim is bounded package-owned
input buffering and incremental record release, not fixed total process memory.

## Validation and confidentiality controls

- Batch and file identifiers pass the established resource-identifier validator
  before URL construction.
- Credentials and gateway URL policy are inherited from `BatchAPIClient`.
- Redirects remain disabled and provider-file GET is the only retried transport
  operation in this path.
- A final non-200 response is rejected before its content stream is consumed.
- Custom adapters must expose callable `content.iter_chunked`; there is no
  whole-body `json()` or `text()` fallback.
- Accepted chunks are `bytes`, `bytearray`, or `memoryview`; memory views are
  accounted with `nbytes`.
- UTF-8 decoding is strict, consistent with JSON interoperability requirements.
- Every nonblank line must decode to one JSON object. Arrays and scalar JSON
  values fail closed.
- Diagnostics contain stable file classification, line/count/limit data, and
  bounded error types. They exclude provider bodies, record content, URLs,
  credentials, and provider identifiers.

## Deterministic assurance evidence

The non-live suite proves:

1. constructor limits reject zero, negatives, booleans, floats, and strings;
2. output and error records retain deterministic order across arbitrary chunks;
3. UTF-8 code units split across chunks decode correctly after line assembly;
4. CRLF, blank lines, and final lines without newline behave deterministically;
5. failed terminal batches can expose an error-only file;
6. incomplete batches and terminal batches without file identifiers fail closed;
7. record limits apply to the combined output and error sequence before the
   excessive record is yielded;
8. both unterminated and newline-terminated oversized lines fail before JSON
   admission;
9. declared and observed file byte limits are independently enforced;
10. missing bounded streams and non-byte chunks fail closed;
11. invalid UTF-8, malformed JSON, and non-object JSON values fail closed;
12. non-success responses are rejected without consuming their body; and
13. the final CR-only blank-line path exits without producing a record.

Protected CI additionally requires Python 3.10, 3.12, and 3.14 unit success,
compilation, Ruff, 100% production statements and branches, 100% public
docstrings, locked dependency freshness, package builds, container builds,
security scanning, and exact-head release acceptance. Stacked-base success is
not reusable after retargeting or prerequisite integration.

No live LLM is material to these deterministic transport and parsing claims, so
`NVIDIA_NIM_API_KEY` is not consumed by the feature test suite.

## Operational guidance

Operators should select limits from an explicit worker memory budget and the
largest legitimate provider record. The line limit must accommodate one complete
JSONL object, not merely expected model text. Record consumers should persist or
transform each record promptly, apply bounded queues, propagate cancellation,
and avoid collecting the iterator into an unbounded list.

A host may impose stricter limits but must not weaken the package validation,
enable redirects, add whole-body fallbacks, or attach record content and provider
identifiers to telemetry. Multi-tenant hosts should persist records under their
own authenticated tenant identity; provider output is never an authorization
source.

The opt-in iterator does not itself persist cursor position or provide exactly
once downstream delivery. A consumer interrupted after processing some records
must reconcile according to its own idempotency key and durable checkpoint
contract.

## Rollback and compatibility

Rollback consists of ceasing use of `StreamingBatchAPIClient`; no database
migration, release-state mutation, or provider-side change is required. Existing
`BatchAPIClient.download_results()` callers retain their aggregate return type.
Removing the public streaming exports after release would be a compatibility
change and requires normal semantic-versioning review.

## Residual risks and non-claims

- JSON decoding of one permitted line can allocate more memory than the encoded
  line size.
- Python runtime and dependency vulnerabilities remain governed by package and
  supply-chain controls.
- Consumer-side buffering, persistence latency, retries, and idempotency are not
  controlled by this iterator.
- Provider files are read from the beginning on each new iterator; durable
  partial-file resume is not claimed.
- OpenTelemetry operation wrappers do not automatically wrap per-record
  iteration. Consumer instrumentation must remain low-cardinality and
  payload-free.
- A malicious provider can consume bounded CPU through many small valid records;
  the total byte and record limits bound the accepted work but do not constitute
  a real-time execution deadline.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format*
(RFC 8259; STD 90). Internet Engineering Task Force.
https://doi.org/10.17487/RFC8259

Internet Engineering Task Force. (2022). *HTTP semantics* (RFC 9110; STD 97).
https://doi.org/10.17487/RFC9110

aiohttp contributors. (2026). *Streaming API: StreamReader.iter_chunked*.
https://docs.aiohttp.org/en/stable/streams.html

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646* (RFC 3629;
STD 63). Internet Engineering Task Force. https://doi.org/10.17487/RFC3629
