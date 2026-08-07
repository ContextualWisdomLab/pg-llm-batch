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
nothing until the supplied checkpoint is reproduced exactly. Changed prefix
content, changed file identity, inserted or removed prefix framing, a different
record at the expected position, or end-of-stream at or before the checkpoint
fails closed before any later record is delivered.

The checkpoint is prefix evidence rather than a complete provider-file
attestation. Mutation or truncation strictly after the acknowledged checkpoint
is outside the reproduced digest and cannot be detected by a successful resume.
A host that requires whole-stream immutability must use a stable provider
validator or authenticated digest, or establish and compare a separate
full-stream manifest under a separately bounded lifecycle.

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

## Durable result-checkpoint persistence boundary

`PostgresBatchResultCheckpointStore` adds an optional package-owned persistence
path without changing the streaming client. The durable identity in
`llm_result_stream_checkpoints` is:

```text
(tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id)
```

The host selects tenant and consumer identity after authentication and
authorization. Provider data never selects either value. Forced row-level
security and tenant-qualified predicates establish defense in depth for ordinary
`NOSUPERUSER NOBYPASSRLS` application roles; generic tenant-controlled SQL and
administrative bypass identities remain outside the isolation claim.

Advancement is compare-and-swap rather than last-writer-wins. Existing state is
read with `FOR UPDATE`; an unequal update must present the exact
`expected_previous` value and increase both logical record and physical-line
positions. Initial missing-row concurrency uses the compound unique key,
`ON CONFLICT ... DO NOTHING`, and locked reconciliation. An identical race is
idempotent, while a different first checkpoint fails as a bounded conflict.

Simple `load()` and `save()` operations own their PostgreSQL transaction.
`load_in_transaction()` and `save_in_transaction()` use a caller-owned
transaction and never commit or roll it back. A host can therefore make local
PostgreSQL record effects and checkpoint advancement atomic. That boundary does
not extend to another database, queue, object store, or external API and is not a
distributed exactly-once protocol; those effects require an outbox, idempotency
key, or explicit reconciliation design.

The package and container migrations are byte-identical. Their object names are
descriptive snake_case, RLS is enabled and forced, and the rollback refuses to
drop a non-empty table. The stored digest remains prefix evidence only; durable
storage does not add provider authentication or full-stream immutability.

## Checkpoint accepted-save audit boundary

`AuditedPostgresBatchResultCheckpointStore` is an opt-in subclass of the durable
store for deployments that require retained application audit evidence rather
than only mutable checkpoint state or best-effort telemetry. Every successful
save call appends one fixed `checkpoint_save_accepted` row in the same PostgreSQL
transaction as the checkpoint operation. Exact idempotent repeats therefore
produce additional accepted-call events; rejected validation or compare-and-swap
operations produce no success event.

The event retains trusted tenant and consumer identity, endpoint and remote batch
key, the complete validated checkpoint coordinates and prefix digest, a
database-generated event identity, and a database timestamp. `recorded_at` uses
PostgreSQL `clock_timestamp()` at row insertion because `NOW()` and
`CURRENT_TIMESTAMP` are transaction-start values and can materially predate an
accepted save in a long caller-owned transaction. Reapplying migration 0008
idempotently resets the default for future rows without rewriting retained audit
evidence. The database wall clock remains inside the operational trust boundary
and is not a cryptographic time attestation. The event excludes provider
payloads, prompts, model output, credentials, DSNs, transport headers, exception
messages, and arbitrary free-form log text. Public reads are tenant-qualified by
the exact checkpoint key, newest-first, and bounded to a strict maximum of 1,000
rows per call.

`llm_result_checkpoint_audit_events` uses forced row-level security under the
same trusted transaction-local tenant setting as checkpoint persistence. A row
trigger rejects ordinary UPDATE and DELETE, while a statement trigger rejects
TRUNCATE because PostgreSQL exposes TRUNCATE triggers only at statement level.
The rollback transaction temporarily relaxes FORCE RLS only so an owner-level
emptiness check can observe every tenant, and refuses destructive rollback while
any audit row remains.

These are append-only controls for ordinary reviewed application roles, not
cryptographic non-repudiation or administrator-proof tamper evidence. PostgreSQL
owners, superusers, `BYPASSRLS` roles, disabled triggers, and physical storage
administrators remain outside the assurance boundary. Stronger deployments must
replicate or export events to separately governed immutable storage or use a
cryptographically protected evidence design.

The package and Docker audit migrations are byte-identical. Fresh bundled
PostgreSQL data directories install audit schema after durable checkpoint schema;
existing volumes require explicit reviewed migration because Docker entrypoint
initialization is not an upgrade mechanism. Audit retention, export, legal hold,
and disposal remain host/operator policy.

## Bounded checkpoint-audit export boundary

`CheckpointAuditPage`, `list_audit_event_page()`, and
`list_audit_event_page_in_transaction()` add an opt-in bounded traversal layer
without changing the existing one-page audit read or database schema. The page
identity remains the exact tenant, consumer, endpoint, and remote-batch key.

Pagination is primary-key keyset traversal rather than offset traversal. The
first page orders by `checkpoint_audit_event_id DESC`; a continuation adds
`checkpoint_audit_event_id < before_audit_event_id` with the same ordering. The
cursor is strict, non-coercive, positive, and bounded by PostgreSQL signed
`BIGINT`. Each query requests at most the validated public limit plus one
lookahead row and exposes at most 1,000 events. The lookahead is used only to
decide whether an older continuation exists.

Rows are not trusted merely because PostgreSQL returned them. Every row is
reconstructed through the public event validator, compared to the exact trusted
request key, and required to be strictly descending by audit identity. A malformed
collection, impossible driver overrun, cross-key row, duplicate identity, or
ascending identity fails closed before a page is exposed.

Keyset traversal prevents later higher-identity inserts from shifting an older
continuation window, but it is not a multi-page database snapshot. Package-owned
page calls may observe different committed database states. A host that requires
one snapshot for a long export pass must begin a caller-owned PostgreSQL
`REPEATABLE READ` or stricter transaction before the first query and repeatedly
call the in-transaction method on that same transaction. The package never
silently changes caller isolation.

Audit identities are database navigation keys, not cryptographic chronology.
Identity sequences may contain gaps and allocation order can differ from commit
order. A cursor therefore does not prove completeness, delivery, authenticity,
retention, or non-repudiation. Hosts still own external immutable/WORM storage,
export receipts, cryptographic manifests where required, reconciliation, legal
hold, and disposal. This boundary exists so those controls can consume retained
evidence without unbounded package memory or offset drift.

## Checkpoint OpenTelemetry observability boundary

`OpenTelemetryCheckpointStore` is an opt-in wrapper around a durable checkpoint
store. It receives a host-owned tracer and meter through dependency injection and
does not configure global providers, processors, samplers, exporters,
collectors, or resources. The wrapped store remains independently usable without
OpenTelemetry and may be the package-owned PostgreSQL store or a compatible
host-owned implementation.

Package-owned spans and metrics use only fixed operation, transaction-owner,
outcome, and finite error-classification attributes. They never contain tenant,
consumer, batch, endpoint, file, digest, cursor, and DSN values, provider
payloads, exception messages, or dynamic exception class names. The package
operation span is deliberately storage-agnostic and does not emit
`db.system.name` or claim OpenTelemetry database-client semantics. Actual
database-client spans and database-system attributes belong to the host or
database instrumentation at the client boundary where the storage technology is
known.

Automatic exception recording and status-on-exception are disabled because a
checkpoint exception may retain protected structured state even when its public
message is bounded. Instead, failed checkpoint spans explicitly set the host
OpenTelemetry API's `StatusCode.ERROR` without a description when the optional
API is available, while successful checkpoint spans leave status Unset. This
preserves standard failure discoverability without exposing exception text in
status descriptions.

The operation counter records completed loads and saves. The duration histogram
uses seconds and a monotonic clock, clamping backward or unavailable clock
evidence to zero. Failures use only `checkpoint_conflict`, `validation_error`, or
`internal_error`; success omits `error.type`. Tracer, meter, span, export-surface,
optional status-code resolution, status mutation, and clock failures are
contained as observer failures. The exact checkpoint return value or application
exception remains authoritative, so best-effort telemetry cannot change
checkpoint operation semantics, compare-and-swap, transaction ownership, commit,
or rollback.

Caller-owned transaction spans cover the package call only and do not claim that
the surrounding transaction later committed. The host owns telemetry retention,
access control, alerting, collector availability, database-client
instrumentation, and any correlation outside this confidential package boundary.

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
advance it after a failed or partially committed consumer transaction. Hosts
must also avoid treating successful prefix reproduction as evidence that an
unseen suffix is complete or immutable. Hosts using the package-owned store may
place local PostgreSQL effects and `save_in_transaction()` on the same caller
cursor; cross-system effects remain host-owned recovery boundaries. Hosts that
choose the audited store gain transaction-coupled accepted-save evidence but
still own identity authorization, retention, export, and stronger tamper-proof
controls where required. Hosts may use bounded audit-page keyset traversal as a
standalone export primitive or embed it into a larger MSA retention workflow;
package pagination itself does not require `contextual-orchestrator`, `naruon`,
or a network export service.

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
framing mutation, changed file identity, truncation at or before the checkpoint,
explicit unseen-suffix limitations, strict pre-network identity validation,
context-managed early close, and SHA-256 framing sensitivity. Durable-store tests
cover strict consumer identity, caller-owned transaction behavior, idempotent
repeat, exact compare-and-swap, stale and regressive writers, equal and unequal
first-writer races, disappearing conflict rows, forced-RLS migration text,
fail-closed rollback, documentation, and live PostgreSQL persistence. Checkpoint
audit tests additionally cover accepted-save transaction coupling, caller-owned
insert-time wall-clock semantics, rejected-save no-success evidence, strict event
revalidation, tenant-qualified bounded reads, package/container migration
identity and idempotent timestamp-default repair, forced RLS, UPDATE/DELETE and
TRUNCATE rejection, fresh-image installation order, fail-closed non-empty
rollback, explicit administrator-tamper exclusions, strict PostgreSQL-BIGINT
identity compatibility, immutable page shape, bounded lookahead, keyset cursor
validation, trusted-key row revalidation, strict descending order, malformed
driver output, and package-owned no-commit page reads. Checkpoint telemetry tests
additionally prove exact delegation, fixed low-cardinality signal attributes,
storage-agnostic operation spans, seconds-based nonnegative duration,
confidential failure classification, explicit Error status without descriptions,
Unset success status, disabled exception recording, and preservation of
application results and exception identity during ordinary tracer, meter, span,
status, and clock failures. Final merge evidence must be regenerated against the
integrated base; successful stacked-base runs are not reusable release evidence.
