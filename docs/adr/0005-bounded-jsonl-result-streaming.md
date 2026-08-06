# ADR 0005: Bound provider JSONL records during incremental retrieval

- **Status:** Accepted
- **Date:** 2026-08-06
- **Decision owners:** ContextualWisdomLab maintainers

## Context

`BatchAPIClient.download_results()` protects provider file downloads with a
strict decoded-byte limit, but it intentionally returns an aggregate object. It
therefore retains the complete UTF-8 body and then every parsed record. A large
but permitted batch can consume substantially more process memory than its wire
representation, especially after Python object expansion. That behavior is
convenient for small standalone jobs but is not a defensible default for large,
shared, or acquisition-reviewed deployments.

JSON defines one value at a time and requires interoperable exchanged text to use
UTF-8. Provider batch files conventionally place one JSON object on each line.
The HTTP adapter already exposes bounded asynchronous byte chunks, so a separate
opt-in iterator can enforce limits before text or object materialization without
changing the established aggregate API.

## Decision

Add `StreamingBatchAPIClient`, a source-compatible subclass of
`BatchAPIClient`, and `BatchResultRecord`, an immutable record envelope.
`iter_batch_records()` shall:

1. validate the batch identifier and retrieve status once through the existing
   bounded control-plane path;
2. reject nonterminal batches and terminal batches without output or error files;
3. process the output file before the error file;
4. preserve the inherited HTTPS, no-redirect, timeout, credential, identifier,
   total-download, and idempotent-GET retry controls;
5. reject non-success file responses before body consumption;
6. consume only bounded byte chunks and count `memoryview.nbytes` accurately;
7. split physical lines incrementally, cap an unterminated or complete line
   before decoding, accept CRLF and a final line without a newline, and ignore
   blank lines;
8. decode each nonblank line with strict UTF-8 and require one JSON object;
9. cap the combined number of output and error records before yielding the
   record that exceeds the limit; and
10. expose only bounded, body-free error metadata.

The aggregate `download_results()` API remains unchanged. Streaming is explicit
because it changes the caller contract from one returned aggregate to an async
iterator whose consumption and persistence policy belongs to the host.

## Consequences

- Library-owned memory is bounded by the configured line buffer, transport chunk,
  decoded control response, and one decoded record at a time rather than the
  complete provider file and record list.
- Hosts can persist or transform records incrementally while retaining standalone
  package operation and modular MSA interoperability.
- Callers remain responsible for downstream backpressure and must not collect all
  yielded records unless they intentionally accept aggregate memory use.
- The file-level total byte limit remains independent for output and error files;
  the record-count limit applies to the combined iterator.
- Existing OpenTelemetry operation wrappers do not implicitly instrument this new
  iterator. Consumer telemetry must remain low-cardinality and payload-free.
- Version `0.1.0` is unchanged; this decision does not authorize publication.

## Alternatives considered

### Replace `download_results()` with an iterator

Rejected because it would break the established public return type and force all
small-job consumers to rewrite their integration.

### Parse the full bounded string with `splitlines()`

Rejected because the decoded string and parsed list still coexist and can exceed
the transport budget through object expansion.

### Depend only on `Content-Length`

Rejected because the field may be absent, malformed, or describe encoded rather
than decoded bytes. Observed bytes remain authoritative.

### Permit arbitrary JSON values per line

Rejected because downstream batch processing expects keyed records and object-only
validation prevents ambiguous arrays and scalars from entering durable workflows.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format*
(RFC 8259; STD 90). Internet Engineering Task Force.
https://doi.org/10.17487/RFC8259

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646* (RFC 3629;
STD 63). Internet Engineering Task Force. https://doi.org/10.17487/RFC3629

aiohttp contributors. (2026). *Streaming API: StreamReader.iter_chunked*.
https://docs.aiohttp.org/en/stable/streams.html
