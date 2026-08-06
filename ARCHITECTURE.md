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

This boundary does not provide durable downstream backpressure. Embedding hosts
own record persistence, queue capacity, cancellation, explicit iterator
lifecycle, and consumer memory. A host that accumulates every yielded record
recreates aggregate memory use.

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
preserve the package's file ordering, resource limits, and deterministic cleanup
contract or define and test a stricter local boundary.

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
non-object records, non-success responses, total-download, byte-line, combined
record, and batch-wide physical line limits across result and error files,
including blank lines, deterministic result/error ordering, and 100% production
statement and branch coverage. Final merge evidence must be regenerated against
the integrated base; successful stacked-base runs are not reusable release
evidence.
