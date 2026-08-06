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

Python's asynchronous iteration protocol does not automatically call
`aclose()` when a consumer exits a bare `async for` loop with `break`. A public
streaming contract therefore also needs explicit lifecycle ownership for early
exit, cancellation, and exception paths rather than relying on nondeterministic
asynchronous-generator finalization.

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
6. consume only non-empty byte chunks no larger than the requested 64 KiB
   transport bound, reject adapters that violate that contract, and count
   `memoryview.nbytes` accurately;
7. split physical lines incrementally, cap an unterminated or complete line
   before decoding, accept CRLF and a final line without a newline, and ignore
   blank lines;
8. decode each nonblank line with strict UTF-8 and require one interoperable JSON
   object without non-finite number extensions or duplicate object names;
9. cap the combined number of output and error records before yielding the
   record that exceeds the limit;
10. expose only bounded, body-free metadata without provider identifiers or
    record content in parser diagnostics or retained exception links; and
11. explicitly close each nested provider-file iterator and provide
    `open_batch_records()` as the supported context-managed owner for consumers
    that may stop before exhaustion.

The aggregate `download_results()` API remains unchanged. Streaming is explicit
because it changes the caller contract from one returned aggregate to an async
iterator whose consumption, persistence, and lifecycle policy belongs to the
host. Direct callers of `iter_batch_records()` must exhaust or explicitly close
the returned iterator.

## Consequences

- Library-owned input buffering is bounded by the configured line buffer,
  requested transport chunk, decoded control response, and one decoded record at
  a time rather than the complete provider file and record list. A custom adapter
  has allocated a returned object before the client can reject it, so adapter
  internals remain outside the package memory claim.
- Zero-progress chunks fail closed before an adapter can sustain an unbounded
  empty-chunk loop inside the package parser.
- Hosts can persist or transform records incrementally while retaining standalone
  package operation and modular MSA interoperability.
- Callers remain responsible for downstream backpressure and must not collect all
  yielded records unless they intentionally accept aggregate memory use.
- Callers that may break early use `open_batch_records()` or own an explicit
  `aclose()` call; a bare loop break is not a cleanup guarantee.
- The file-level total byte limit remains independent for output and error files;
  the record-count limit applies to the combined iterator.
- Duplicate JSON object names and Python-compatible `NaN`/infinity extensions are
  rejected to avoid ambiguous or non-interoperable durable records.
- Decoder failures are translated after the active exception handler exits, so
  exported sanitized errors do not retain provider-controlled bytes or text in
  `__cause__` or `__context__`.
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

### Trust custom adapters to honor `iter_chunked(n)`

Rejected because the client can cheaply validate that each observed chunk is
non-empty and within the requested ceiling before copying it into package-owned
line buffering. The checks do not control memory already allocated inside the
adapter, but they preserve the package boundary and guarantee forward byte
progress for yielded chunks.

### Rely on bare-loop asynchronous-generator cleanup

Rejected because `break` does not call `aclose()`. Garbage collection and event
loop finalization are nondeterministic lifecycle mechanisms and cannot support a
commercial operator contract for response release.

### Permit arbitrary or ambiguous JSON values per line

Rejected because downstream batch processing expects keyed records. Object-only,
finite-number, and unique-name validation prevents ambiguous arrays, scalars, or
implementation-specific objects from entering durable workflows.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format*
(RFC 8259; STD 90). Internet Engineering Task Force.
https://doi.org/10.17487/RFC8259

Python Software Foundation. (2026). *Asynchronous generator-iterator methods*.
https://docs.python.org/3/reference/expressions.html#asynchronous-generator-iterator-methods

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646* (RFC 3629;
STD 63). Internet Engineering Task Force. https://doi.org/10.17487/RFC3629

aiohttp contributors. (2026). *Streaming API: StreamReader.iter_chunked*.
https://docs.aiohttp.org/en/stable/streams.html
