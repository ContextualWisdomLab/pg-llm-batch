# Architecture

## Deployment boundary

`pg-llm-batch` remains independently deployable and embeddable. PostgreSQL owns
configuration, encrypted secrets, token counting, JSONL payloads, and durable
provider lifecycle state. Provider HTTP behavior remains behind
`BatchAPIClient`, while host services may inject credential, observation-order,
and lifecycle-persistence seams without changing provider semantics.

## Durable lifecycle tenancy

`DurableBatchAPIClient` is the backward-compatible standalone facade.
`TenantDurableBatchAPIClient` requires a tenant scope selected by a trusted host
after authentication and authorization. The durable business identity is:

```text
(tenant_scope, endpoint_alias, remote_batch_id)
```

Package reads and writes bind the validated scope with parameterized,
transaction-local `set_config('pg_llm_batch.tenant_scope', ..., true)`.
PostgreSQL row-level security is enabled and forced, so missing context is
default-deny for ordinary application roles. PostgreSQL superusers and roles
with `BYPASSRLS` remain administrative escape hatches and must not be used as
application identities.

The custom setting is part of a **trusted application boundary**. It is not a
credential and is not a substitute for authentication, authorization,
SQL-injection prevention, or restricted direct database access. A role capable
of arbitrary SQL can call `set_config` with an arbitrary tenant scope. CWL hosts
must therefore expose tenant lifecycle operations through parameterized package
APIs or a separately reviewed identity-to-role interface, not a generic SQL
surface.

Provider metadata, endpoint aliases, provider resource identifiers, payloads,
model output, and transport headers never select tenant authorization context.

## Migration and rollback

Legacy lifecycle rows are backfilled to `standalone` without deletion or
identity merging. The prior endpoint/provider unique key is replaced by a
tenant-qualified key. The owner-enforcement transition, backfill, constraint
migration, and forced-RLS restoration execute in one PostgreSQL anonymous block
so psql autocommit cannot commit an intermediate owner-bypass state.

Enabling RLS changes the behavior of direct SQL integrations: an ordinary role
that does not bind an authorized transaction-local scope sees no lifecycle
rows. Those integrations must move to `get_remote_batch_state`,
`get_tenant_remote_batch_state`, or a reviewed tenant-binding database interface
before deployment.

Rollback to the former two-column key is unsafe until an operator proves that no
`(endpoint_alias, remote_batch_id)` pair exists in more than one tenant scope.
The packaged schema and Docker initialization schema are maintained as exact
mirrors and must be reapplied successfully more than once.

## Reproducible release evidence boundary

Release acceptance is a read-only control-plane boundary. Two clean exact-source
builds are compared before maintainers consider versioning, publication,
attestation, or release authorization. The verifier accepts exactly one wheel and
one source distribution and enumerates at most three directory entries.

Release directories and artifact names are concurrent untrusted filesystem
inputs. The verifier opens `/` for absolute paths or `.` for relative paths and
walks each component with descriptor-relative `O_DIRECTORY | O_NOFOLLOW`.
Artifact entries are opened relative to the held final directory with
`O_NOFOLLOW | O_NONBLOCK`, required to be regular files, and streamed through
bounded `os.read`. Size and SHA-256 are derived from that same open file
description. Device, inode, file type, size, modification time, and change time
must remain stable across the read. The verifier then re-enumerates the same held
directory descriptor and rejects membership or same-name object-identity drift.

This openat-style boundary removes pathname check-then-open races from the
release identity decision. It does not prevent a same-UID process from changing
an object after verification returns, so the workflow also relies on governed
runner and workspace isolation. Unsupported runtimes fail closed rather than
falling back to pathname verification.

The canonical manifest writer remains a separate descriptor-relative operation:
it creates an owned mode-0600 temporary entry, synchronizes bytes, atomically
renames within the pinned final parent, and synchronizes the directory entry.
Neither verifier nor writer publishes, signs, attests, approves, or authorizes
reuse of pull-request artifacts.

## Bounded provider result boundary

`BatchAPIClient.download_results()` remains the backward-compatible aggregate
retrieval facade. `StreamingBatchAPIClient` is the opt-in memory-safety boundary
for large provider result and error files. It reuses the same credential, URL,
timeout, no-redirect, identifier, retry, and decoded-byte controls while parsing
JSONL incrementally.

The streaming client validates one terminal status snapshot, then consumes the
output file before the error file. It holds at most one non-empty bounded
transport chunk, one bounded physical line, and one decoded JSON object in
library-owned memory. A strict per-file decoded-byte limit, per-line byte limit,
and combined record limit fail closed before excessive data is yielded. Missing
streams, non-byte chunks, zero-progress chunks, and chunks above the requested
ceiling are rejected before package-owned line buffering. Non-success file
responses are rejected before provider body consumption, and every nonblank line
must be strict UTF-8 containing one unambiguous JSON object.

`max_jsonl_physical_lines` establishes one batch-wide physical line budget
shared by result and error files. Every newline-terminated line and any final
unterminated line consumes the budget before UTF-8 decoding or JSON parsing;
blank lines count even though they do not yield records. This closes a bounded
CPU-amplification gap that per-line bytes and yielded-record limits alone do not
cover.

Decoder failures are translated after the provider decoder's active exception
handler exits. The sanitized public error therefore does not retain the decoder
exception—and its provider-controlled bytes or text—through `__cause__` or
`__context__`.

Stream lifetime is a separate control-plane boundary. The outer public iterator
owns each nested provider-file iterator through `contextlib.aclosing`.
`open_batch_records()` owns the outer iterator and closes it in `finally`, making
it the supported API when a consumer may stop early. A bare `async for` break
does not call `aclose()` and is not a deterministic HTTP-response release
mechanism.

Transport retry eligibility ends before the response is handed to a body
consumer. Request acquisition and retryable HTTP-status decisions may retry only
while no response body has been exposed. Once body iteration begins, a payload
or response-close transport failure closes that response once, becomes a bounded
body-free `GatewayError`, and never reopens the provider file or replays records
already yielded. This boundary prevents an idempotent request retry from becoming
non-idempotent application delivery after partial consumption.

This boundary does not provide durable downstream backpressure. Embedding hosts
own record persistence, queue capacity, cancellation, explicit iterator
lifecycle, and consumer memory. A host that accumulates every yielded record
recreates aggregate memory use.

## Resumable result checkpoint boundary

`iter_checkpointed_batch_records()` and
`open_checkpointed_batch_records()` add an opt-in application-recovery boundary
without changing aggregate or non-checkpointed streaming behavior. Each validated
record is paired with an immutable versioned `BatchResultCheckpoint` that a host
may persist after its corresponding record effects are durable.

Checkpoint identity is SHA-256 over a domain-separated, explicitly
length-prefixed frame sequence. The sequence binds the exact validated batch
identifier and pre-normalized endpoint alias, ordered result/error file kind and
validated provider file identifier, every raw physical line byte sequence, its
file-local line number, and whether LF terminated the line. Blank lines and CR
bytes in CRLF input affect checkpoint identity; transport chunk boundaries do
not. The checkpoint also carries batch-wide physical-line and record positions
for bounded reconciliation and diagnostics.

Resume deliberately starts at byte zero instead of depending on HTTP Range,
ETag, or provider-specific validator behavior. It rereads and parses the prefix
under all existing total-byte, line-byte, physical-line, record, timeout,
retry-handoff, strict-JSON, and deterministic-close controls. The iterator yields
nothing until the supplied checkpoint is reproduced exactly. Changed content,
changed file identity, inserted or removed framing, a different record at the
expected position, or end-of-stream before the position fails closed before any
later record is delivered.

The digest is deterministic change-detection evidence under FIPS 180-4, not an
authentication or authorization mechanism. It is not a signature, MAC, provider
attestation, tenant credential, or complete exactly-once protocol. The embedding
host owns caller authentication, tenant and endpoint authorization, checkpoint
store tamper/rollback protection, and atomic coordination between record effects
and checkpoint advancement. A host needing authenticated checkpoint storage may
wrap the serialized checkpoint in its own HMAC, signature, append-only log, or
transactional database control.

An incompatible framing change requires a new checkpoint schema version and an
explicit compatibility/migration decision. The current feature adds no database
object and preserves standalone and modular MSA deployment.

## Modular interoperability

CWL hosts such as `contextual-orchestrator` and `naruon` supply tenant context
only after their own authentication and authorization boundary. The package does
not require either host and retains standalone operation. When embedded, tenant
scope is a local control-plane identity and not model- or provider-returned data.

Release evidence also remains standalone. Host modules may consume the bounded
manifest only as review input and must not reinterpret it as provenance,
publication authority, or an integrated-release attestation.

Streaming retrieval also remains standalone. Host modules may persist each
`BatchResultRecord` into their own tenant-qualified queue or database, but must
preserve the package's file ordering, resource limits, retry-handoff boundary,
and deterministic cleanup contract or define and test a stricter local boundary.
For checkpointed delivery, hosts must persist the complete checkpoint in the
same trusted tenant and endpoint context as the record effects and must not
advance it after a failed or partially committed consumer transaction.

## Verification boundary

Deterministic gates cover strict tenant validation, standalone compatibility,
tenant-qualified SQL parameters, current-state reconciliation, migration
idempotency, malformed database rows, default-deny policy text, schema
mirroring, operator documentation, and 100% production statement and branch
coverage. Live PostgreSQL isolation tests use a `NOSUPERUSER NOBYPASSRLS` role
and prove that identical provider identifiers in different tenants remain
independently addressable and mutually invisible when access occurs through the
trusted package boundary. They do not claim isolation after arbitrary SQL is
granted.

Release security tests cover symlinked parents, parent traversal, artifact
replacement after enumeration, in-place mutation during streaming hash,
directory-membership and same-name identity drift, bounded scan and error
behavior, descriptor capability failure, Python compatibility, and 100%
production statement and branch coverage. Streaming tests cover split chunks,
CRLF and final-line parsing, invalid and zero-progress streams, encoding and JSON
failures, exception-context sanitization, nested and early-close lifecycle,
post-handoff payload and response-close failures, no-retry/no-replay behavior,
non-object records, non-success responses, total-download, byte-line, combined
record, and batch-wide physical line limits across result and error files,
including blank lines, deterministic result/error ordering, and 100% production
statement and branch coverage. Checkpoint tests additionally cover chunk
independence, exact resume without acknowledged-record replay, final-checkpoint
completion, result-prefix binding across error-file checkpoints, content and
framing mutation, changed file identity, truncation, strict pre-network identity
validation, context-managed early close, and SHA-256 framing sensitivity. Final
merge evidence must be regenerated against the integrated base; successful
stacked-base runs are not reusable release evidence.
