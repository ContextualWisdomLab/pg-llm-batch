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
    max_jsonl_physical_lines=100_000,
) as client:
    async with client.open_batch_records("batch-123", "default") as records:
        async for item in records:
            persist(item.file_kind, item.record)
            if consumer_should_stop():
                break
```

`open_batch_records()` is the supported lifecycle boundary when a consumer may
stop early. Leaving its `async with` block explicitly closes the outer iterator,
the active provider-file iterator, and the HTTP response context. A bare
`async for` loop over `iter_batch_records()` does not receive an automatic
`aclose()` call from Python when the loop breaks; callers using that lower-level
method must exhaust it or close it explicitly.

Records are emitted in deterministic provider-file order: all output records,
then all error records. A failed batch that exposes only an error file is valid.
An incomplete batch or terminal batch with neither file identifier fails closed.

## Resumable checkpoints

Use the checkpointed API when a host durably applies records and may restart
before the complete provider stream is consumed:

```python
from pg_llm_batch import BatchResultCheckpoint, StreamingBatchAPIClient

resume_after: BatchResultCheckpoint | None = load_checkpoint()

async with StreamingBatchAPIClient(dsn, credentials_provider) as client:
    async with client.open_checkpointed_batch_records(
        "batch-123",
        "default",
        resume_after=resume_after,
    ) as records:
        async for item in records:
            with host_transaction():
                apply_record(item.file_kind, item.record)
                store_checkpoint(item.checkpoint)
```

Each `CheckpointedBatchResultRecord` contains the decoded record and an immutable
`BatchResultCheckpoint`. Persist the complete checkpoint only after the record's
application effects are durable. Exactly-once behavior requires a host-owned
transaction, idempotency key, or equivalent proof that atomically coordinates
record effects and checkpoint advancement.

A checkpoint binds:

- schema version, exact validated batch identifier, and pre-normalized endpoint
  alias;
- ordered provider file kind and validated file identifier;
- file-local physical line, batch-wide physical line, and batch-wide record
  positions; and
- a SHA-256 digest of a domain-separated, length-prefixed encoding of the full
  physical stream prefix through that record.

Physical framing is part of identity. Blank lines, CR bytes in CRLF input,
newline termination, file transitions, and provider file identifiers affect the
digest. HTTP chunk boundaries do not.

Resume performs a bounded rescan from byte zero. No later record is delivered
until the supplied checkpoint is reproduced exactly. A changed prefix, changed
provider file identity, inserted or removed framing, unexpected record at the
checkpoint position, or truncation at or before the checkpoint fails closed. The
rescan preserves all existing byte, line, physical-line, record, timeout,
identifier, retry-handoff, parser, and deterministic-close controls.

This checkpoint verifies only the reproduced prefix. Mutation or truncation
strictly after the acknowledged checkpoint is outside that evidence and can end
a resumed stream without a mismatch. Hosts requiring whole-stream immutability
must use a stable provider validator or authenticated digest, or perform a
separate full-stream manifest pass before accepting the stream as complete.

The checkpoint is change-detection evidence, not authentication. SHA-256 does
not protect a checkpoint store from an actor able to rewrite both checkpoint and
provider input. Hosts must authenticate callers, authorize tenant and endpoint
access, protect checkpoint storage against tampering and rollback, and surface a
mismatch as an operator reconciliation event rather than silently advancing it.
See [ADR 0006](adr/0006-resumable-result-checkpoints.md) and the
[assurance record](doctoring/resumable-result-checkpoints.md).

## Package-owned durable checkpoint storage

Apply the dedicated migration after the base package schema:

```python
from pg_llm_batch import (
    PostgresBatchResultCheckpointStore,
    apply_result_checkpoint_schema,
)

apply_result_checkpoint_schema(dsn)
checkpoint_store = PostgresBatchResultCheckpointStore(
    dsn,
    tenant_scope="tenant-a",
)
```

For simple standalone processing, `load()` and `save()` own their PostgreSQL
transactions:

```python
resume_after = checkpoint_store.load("invoice-worker", "batch-123", "default")

async with client.open_checkpointed_batch_records(
    "batch-123",
    "default",
    resume_after=resume_after,
) as records:
    async for item in records:
        apply_idempotent_record(item.record)
        resume_after = checkpoint_store.save(
            "invoice-worker",
            item.checkpoint,
            expected_previous=resume_after,
        )
```

When record effects are stored in the same PostgreSQL database, use a
caller-owned transaction so the effect and acknowledgement cannot split:

```python
import psycopg

with psycopg.connect(dsn) as connection:
    with connection.cursor() as cursor:
        apply_record_with_cursor(cursor, item.record)
        resume_after = checkpoint_store.save_in_transaction(
            cursor,
            "invoice-worker",
            item.checkpoint,
            expected_previous=resume_after,
        )
    connection.commit()
```

`save_in_transaction()` never commits or rolls back the caller's cursor. An exact
repeat is idempotent. Every different durable row requires the exact
`expected_previous` value and strictly increasing record and physical-line
positions. A stale, forked, regressive, missing, or conflicting first writer
raises `CheckpointConflictError` without overwrite.

Tenant scope and consumer identity must come from the host's authenticated and
authorized control plane. Production application roles must be
`NOSUPERUSER NOBYPASSRLS`, must not expose arbitrary tenant-controlled SQL, and
must have only the table and schema privileges required by the deployment.
Forced row-level security is defense in depth, not a credential or substitute for
authorization.

This is not a distributed exactly-once protocol. A queue, another database,
object store, webhook, or provider-side effect cannot share the local PostgreSQL
transaction and still requires a stable idempotency key, transactional outbox, or
operator reconciliation. Durable storage also does not authenticate the
checkpoint or prove full-stream immutability after the reproduced prefix.

The rollback file
`pg_llm_batch/migrations/rollback/0007_result_stream_checkpoints.sql` refuses to
drop a non-empty table. Export or reconcile acknowledgement evidence before an
operator deliberately removes it. See
[ADR 0007](adr/0007-durable-result-checkpoint-store.md) and the
[durable-store assurance record](doctoring/durable-result-checkpoint-store.md).

## Resource and trust boundaries

- The inherited total decoded-byte limit is enforced independently for each
  provider file from both declared and observed bytes.
- `max_jsonl_line_bytes` caps one physical line before UTF-8 decoding or JSON
  parsing, including a final line without a newline.
- `max_jsonl_records` caps the combined output-plus-error record count for one
  iterator, including records rescanned before a supplied checkpoint.
- `max_jsonl_physical_lines` caps the batch-wide physical line count shared by
  result and error files. Every newline-terminated line and a final unterminated
  line count before decoding; blank lines consume this budget even though they
  do not yield records. Resumed scans consume the same budget from byte zero.
- Response data is consumed only through `content.iter_chunked(64 KiB)`. An
  adapter that omits the interface, emits a non-byte or empty chunk, or yields a
  chunk larger than the requested 64 KiB fails closed before package-owned line
  buffering. Empty chunks are rejected because they make no byte progress and
  could otherwise sustain an unbounded adapter loop without reaching a byte cap.
- Redirects remain disabled, provider identifiers remain validated before URL
  construction, and only idempotent GET transport operations use bounded retry.
  Retry eligibility ends before the response is handed to the body consumer.
  Once body iteration begins, payload and response-close failures close the
  active response once and do not reopen the file or replay yielded records.
- Every nonblank line must be strict UTF-8 and decode to one interoperable JSON
  object. Arrays, scalars, non-finite number extensions, duplicate object names,
  malformed JSON, and invalid UTF-8 are rejected with body-free diagnostics.
- Sanitized parser errors are raised outside the provider decoder's active
  exception handler, so their exported cause and context do not retain decoder
  exceptions that reference provider-controlled bytes or text.
- Parser and checkpoint diagnostics exclude provider batch and file identifiers
  as well as record content.
- Non-success file responses are rejected before reading the provider-controlled
  body.

The iterator bounds library-owned buffering, not downstream consumer behavior.
A caller that appends every yielded record to a list recreates aggregate memory
use and must size its own process accordingly. Cancellation closes active
response contexts through generator cleanup; planned early exit should use the
context-managed API for deterministic closure.

A post-handoff transport failure is terminal for the current iterator. Starting
a new non-checkpointed iterator reads the provider file from byte zero and may
replay records. Starting a checkpointed iterator with the last durably committed
checkpoint rescans and suppresses acknowledged records only after exact prefix
verification.

## Compatibility and observability

The streaming client subclasses `BatchAPIClient`, so credentials, gateway URL
validation, timeouts, pre-handoff retry policy, and session lifecycle remain
identical. The package-owned checkpoint store is optional; custom host stores
remain supported, and the streaming client itself does not open the checkpoint
table.

Embedding hosts may store each record and checkpoint in their own durable queue,
tenant-qualified database, transactional outbox, or bounded transformation
pipeline. The existing OpenTelemetry subclass does not automatically wrap this
opt-in iterator or checkpoint store. Hosts that need per-record,
resume-reconciliation, or checkpoint-conflict telemetry should instrument the
consumer boundary with low-cardinality attributes and must not attach provider
identifiers, checkpoint digests, prompts, response bodies, model output, or raw
database exception text.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) data interchange format*
(RFC 8259; STD 90). Internet Engineering Task Force.
https://doi.org/10.17487/RFC8259

National Institute of Standards and Technology. (2015). *Secure Hash Standard
(SHS)* (Federal Information Processing Standards Publication 180-4).
https://doi.org/10.6028/NIST.FIPS.180-4

Python Software Foundation. (2026). *hashlib—Secure hashes and message digests*
(Python 3.14 documentation). https://docs.python.org/3.14/library/hashlib.html

Yergeau, F. (2003). *UTF-8, a transformation format of ISO 10646* (RFC 3629;
STD 63). Internet Engineering Task Force. https://doi.org/10.17487/RFC3629

aiohttp contributors. (2026). *Streaming API: StreamReader.iter_chunked*.
https://docs.aiohttp.org/en/stable/streams.html
