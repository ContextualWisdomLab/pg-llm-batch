# Doctoring: bounded JSONL result streaming

## Decision and assurance scope

This doctoring record supports ADR 0005 and the opt-in
`StreamingBatchAPIClient`. It documents the claim that library-owned retrieval
memory and parser work are bounded independently of a provider file's permitted
total size. The claim is limited to the package-owned HTTP and JSONL parsing
path; downstream queues, persistence adapters, transformations, and callers
remain separate trust and resource boundaries.

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
- a large sequence of blank physical lines consuming parser-loop CPU without
  consuming the emitted-record budget;
- chunk boundaries splitting UTF-8 code units or JSON tokens;
- a custom adapter ignoring the requested chunk ceiling;
- a custom adapter yielding an unbounded sequence of empty chunks without making
  byte progress;
- missing, false, negative, or encoded-length metadata misleading a byte budget;
- non-byte adapter chunks bypassing byte accounting;
- malformed UTF-8, non-finite number extensions, duplicate object names, JSON
  arrays or scalars, or recursively pathological JSON entering durable workflows;
- decoder exceptions retaining provider bytes or text through exported exception
  causes or contexts;
- redirect-based destination changes or unsafe provider identifiers altering the
  request boundary;
- non-success response bodies being read into memory or leaked through errors;
- a transport failure after response handoff causing an idempotent GET retry from
  byte zero, duplicate already-yielded records, or a second context-manager yield
  while handling the first body exception;
- an early consumer loop exit retaining an active HTTP response because Python's
  asynchronous iteration protocol does not automatically call `aclose()` on
  `break`;
- result and error files jointly exceeding a host's expected line or record
  budget; and
- a caller collecting every yielded record and recreating aggregate memory use.

## Normative resource contract

| Boundary | Default | Enforcement point | Failure behavior |
| --- | ---: | --- | --- |
| Control-plane JSON response | 1 MiB | inherited bounded status reader | fail closed before object acceptance |
| One provider result or error file | 128 MiB decoded bytes | declared and observed byte accounting | fail closed with body-free byte counts |
| One physical JSONL line | 1 MiB | before UTF-8 decoding and JSON parsing | fail closed with line number and bounded counts |
| One batch's physical lines | 100,000 lines | batch-wide before parsing, shared by result and error files | fail closed with file line, batch count, and configured limit |
| One batch iterator | 100,000 objects | before yielding the first excessive record | fail closed with count and configured limit |
| One HTTP stream chunk | 64 KiB | requested and observed `iter_chunked` size | reject absent, empty, non-byte, or oversized chunks |
| Provider-file retry handoff | one response body | before yielding the response to a body consumer | after handoff close once, fail once, never restart or replay |

Each provider file receives an independent total-download budget. The
`max_jsonl_physical_lines` and record budgets are combined across the
deterministic output-then-error sequence. Every newline-terminated line and any
final unterminated line consumes the physical-line budget before decoding;
blank physical lines do not consume the record budget but do consume the line
budget. Limits are strict positive integers; booleans and coercible strings are
rejected rather than normalized.

The implementation may temporarily hold one bounded transport chunk, one bounded
line, one decoded text value, and one decoded JSON object. Python allocator
behavior, JSON object expansion, and a caller's retained references prevent a
claim of an exact resident-set-size ceiling. The defensible claim is bounded
package-owned input buffering, bounded physical-line processing, and incremental
record release, not fixed total process memory.

## Validation, lifecycle, and confidentiality controls

- Batch and file identifiers pass the established resource-identifier validator
  before URL construction.
- Credentials and gateway URL policy are inherited from `BatchAPIClient`.
- Redirects remain disabled and provider-file GET is the only retried transport
  operation in this path.
- Request acquisition and retryable response-status handling finish before
  response handoff. A payload or response-close transport failure after handoff
  closes the active response once, becomes a bounded body-free `GatewayError`,
  performs no retry sleep, and does not reopen the file or replay records.
- A final non-200 response is rejected before its content stream is consumed.
- Custom adapters must expose callable `content.iter_chunked`; there is no
  whole-body `json()` or `text()` fallback.
- Accepted chunks are `bytes`, `bytearray`, or `memoryview`; memory views are
  accounted with `nbytes`, every observed chunk must be non-empty, and every
  observed chunk must remain within the requested 64 KiB ceiling before
  package-owned line buffering.
- A per-iterator budget object counts physical lines across both files before
  any UTF-8 or JSON operation. The counter is local to one iterator and is not
  shared between concurrent batch consumers.
- UTF-8 decoding is strict, consistent with JSON interoperability requirements.
- Every nonblank line must decode to one JSON object. Arrays, scalar JSON values,
  Python-compatible non-finite number extensions, and duplicate object names fail
  closed.
- Sanitized parser errors are raised after leaving the decoder's active exception
  handler, so exported `GatewayError` cause and context links do not retain the
  provider-controlled decoder exception.
- Diagnostics contain stable file classification, line/count/limit data, and
  bounded error types. They exclude provider bodies, record content, URLs,
  credentials, and provider identifiers.
- `open_batch_records()` owns the outer async generator and closes it in `finally`.
  The outer generator owns each nested provider-file generator through
  `contextlib.aclosing`, so early context exit closes the active response exactly
  once. Direct `iter_batch_records()` callers must exhaust or explicitly close
  the iterator.

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
8. the physical-line budget is shared across output and error files and counts
   blank lines before parsing;
9. both unterminated and newline-terminated oversized lines fail before JSON
   admission;
10. declared and observed file byte limits are independently enforced;
11. missing bounded streams, non-byte chunks, empty chunks, and chunks larger
    than the requested transport ceiling fail closed;
12. invalid UTF-8, malformed JSON, non-finite numbers, duplicate object names,
    and non-object JSON values fail closed;
13. sanitized invalid-UTF-8 and malformed-JSON errors expose no decoder cause or
    context object;
14. parser diagnostics do not disclose valid provider batch identifiers;
15. non-success responses are rejected without consuming their body;
16. the final CR-only blank-line path exits without producing a record;
17. a context-managed consumer that breaks after one record closes the active
    provider response exactly once;
18. nested provider-file iterators are explicitly closed when the outer iterator
    is closed;
19. a post-handoff payload failure performs one GET, zero retry sleeps, one
    response close, and one bounded public failure;
20. a response-close transport failure after successful handoff follows the same
    no-retry boundary; and
21. a streaming body that yields one valid record and then fails never restarts
    from byte zero or duplicates that record.

Protected CI additionally requires Python 3.10, 3.12, and 3.14 unit success,
compilation, Ruff, 100% production statements and branches, 100% public
docstrings, locked dependency freshness, package builds, container builds,
security scanning, and exact-head release acceptance. Stacked-base success is
not reusable after retargeting or prerequisite integration.

No live LLM is material to these deterministic transport and parsing claims, so
`NVIDIA_NIM_API_KEY` is not consumed by the feature test suite.

## Operational guidance

Operators should select limits from an explicit worker memory and CPU budget and
the largest legitimate provider record. The line-byte limit must accommodate one
complete JSONL object, not merely expected model text. The physical-line limit
must cover the expected sum of result and error lines, including legitimate blank
lines, while remaining low enough to prevent newline-amplification workloads.
Record consumers should persist or transform each record promptly, apply bounded
queues, propagate cancellation, and avoid collecting the iterator into an
unbounded list.

Consumers that can stop before exhausting the stream must use
`open_batch_records()` as an `async with` boundary or otherwise call `aclose()`
explicitly. A bare `async for` break is not a deterministic cleanup contract.

A post-handoff transport failure is terminal for the current iterator. Operators
must not transparently restart the provider file unless a host-owned durable
checkpoint and idempotency policy can prove that already-consumed records will
not be duplicated.

A host may impose stricter limits but must not weaken the package validation,
enable redirects, add whole-body fallbacks, accept zero-progress adapter chunks,
or attach record content and provider identifiers to telemetry. Multi-tenant
hosts should persist records under their own authenticated tenant identity;
provider output is never an authorization source.

The opt-in iterator does not itself persist cursor position or provide exactly
once downstream delivery. A consumer interrupted after processing some records
must reconcile according to its own idempotency key and durable checkpoint
contract.

## Rollback and compatibility

Rollback consists of ceasing use of `StreamingBatchAPIClient`; no database
migration, release-state mutation, or provider-side change is required. Existing
`BatchAPIClient.download_results()` callers retain their aggregate return type.
Removing the public streaming exports, deterministic context-manager method, or
accepted constructor limits after release would be a compatibility change and
requires normal semantic-versioning review.

## Residual risks and non-claims

- JSON decoding of one permitted line can allocate more memory than the encoded
  line size.
- A custom adapter has already allocated its returned chunk before the client can
  reject an oversized value; the package does not control adapter internals.
- An adapter that never yields control is outside the byte-progress check and
  remains bounded by the inherited request timeout where the adapter honors it.
- Python runtime and dependency vulnerabilities remain governed by package and
  supply-chain controls.
- Consumer-side buffering, persistence latency, retries, and idempotency are not
  controlled by this iterator.
- Provider files are read from the beginning on each new iterator; durable
  partial-file resume is not claimed.
- OpenTelemetry operation wrappers do not automatically wrap per-record
  iteration. Consumer instrumentation must remain low-cardinality and
  payload-free.
- A malicious provider can consume bounded CPU through many small valid or blank
  lines; the total byte, physical-line, and record limits bound accepted work but
  do not constitute a real-time execution deadline.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format*
(RFC 8259; STD 90). Internet Engineering Task Force.
https://doi.org/10.17487/RFC8259

Internet Engineering Task Force. (2022). *HTTP semantics* (RFC 9110; STD 97).
https://doi.org/10.17487/RFC9110

MITRE Corporation. (2026). *CWE-400: Uncontrolled resource consumption*
(CWE version 4.20). https://cwe.mitre.org/data/definitions/400.html

OWASP Foundation. (2023). *API4:2023 unrestricted resource consumption*.
https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/

aiohttp contributors. (2026). *Streaming API: StreamReader.iter_chunked*.
https://docs.aiohttp.org/en/stable/streams.html

Python Software Foundation. (2026). *Asynchronous generator-iterator methods*.
https://docs.python.org/3/reference/expressions.html#asynchronous-generator-iterator-methods

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646* (RFC 3629;
STD 63). Internet Engineering Task Force. https://doi.org/10.17487/RFC3629
