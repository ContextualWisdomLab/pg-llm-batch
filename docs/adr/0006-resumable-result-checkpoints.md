# ADR 0006: Resumable provider-result checkpoints

- **Status:** Accepted
- **Date:** 2026-08-06
- **Decision owners:** ContextualWisdomLab maintainers
- **Supersedes:** None

## Context

`StreamingBatchAPIClient` bounds provider-result memory and prevents automatic
post-handoff request retry, but an embedding host can still restart after it has
durably committed one or more records. Reopening the provider file from byte
zero without package-owned resume evidence can replay acknowledged records.
Persisting only a record number is insufficient: provider output can be replaced,
truncated, reframed with blank lines, or changed before that logical position.

The package cannot assume provider support for byte ranges, entity tags, stable
content-length values, or authenticated content digests across all
OpenAI-compatible gateways. It also cannot own every host's durable transaction,
tenant authorization, or exactly-once sink.

## Decision

Add an opt-in immutable `BatchResultCheckpoint` and
`CheckpointedBatchResultRecord` contract to `StreamingBatchAPIClient`.

For every yielded nonblank JSON object, the client emits a versioned checkpoint
that contains:

- the exact validated batch and endpoint alias;
- ordered provider file kind and validated file identifier;
- physical line number within the current file;
- batch-wide physical line and record positions; and
- a lowercase SHA-256 digest of a domain-separated, length-prefixed encoding of
  the complete bounded physical stream prefix through that record.

The digest input binds the batch and endpoint identity, every ordered provider
file transition and file identifier, every physical line byte sequence, and
whether each line was newline terminated. Blank lines and CR bytes in CRLF input
therefore affect the digest even though blank lines do not yield records and CR
is removed before JSON parsing.

`resume_after` performs a bounded rescan from byte zero under the existing
credential, URL, timeout, retry-handoff, total-byte, line-byte, physical-line,
record-count, parsing, and response-lifecycle controls. No record is yielded
until the supplied checkpoint is reproduced exactly. A changed prefix, changed
file identity, unexpected record at the checkpoint position, or a stream
truncated at or before the checkpoint fails closed with bounded body-free
diagnostics.

Resume does not use HTTP range requests. This keeps the behavior portable across
OpenAI-compatible providers and ensures that all preceding framing and file
identity are revalidated. The cost is linear read and parse work through the
checkpoint position.

This is prefix evidence, not a whole-file attestation. Mutation or truncation
strictly after the acknowledged checkpoint is not detectable because those bytes
and records are outside the reproduced prefix. Hosts that require whole-stream
immutability must rely on a stable provider validator or authenticated digest, or
establish and compare a separate full-stream manifest before delivery.

## Security and trust boundary

SHA-256 is used as deterministic change-detection evidence under FIPS 180-4. The
checkpoint is **not** a message authentication code, signature, provider
attestation, tenant credential, authorization decision, or protection against a
host that can rewrite both the checkpoint and provider stream. Embedding hosts
must authenticate callers, authorize tenant and endpoint access, protect their
checkpoint store against tampering and rollback, and commit a checkpoint in the
same durable application transaction as the corresponding record effects when
exactly-once behavior is required.

Checkpoint identity validation occurs before credential resolution or network
I/O. Provider-controlled identifiers and record data remain excluded from
public mismatch diagnostics. Existing aggregate and non-checkpointed streaming
APIs remain source compatible.

## Consequences

### Positive

- A host can resume after its last acknowledged record without replaying that
  record when the provider prefix is unchanged.
- File replacement, truncation at or before the checkpoint, framing changes, and
  prefix mutation are detected before a later record is delivered.
- Checkpoints are serializable plain data and do not require PostgreSQL schema
  changes or another CWL service.
- Chunk boundaries do not affect checkpoint identity.

### Negative

- Resume rereads and parses the prefix and therefore consumes provider bandwidth
  and CPU proportional to the checkpoint position.
- The host remains responsible for durable checkpoint storage and atomic sink
  coordination.
- An unkeyed digest cannot authenticate an adversarial checkpoint store.
- Successful checkpoint reproduction does not attest an unseen suffix after the
  acknowledged record.

## Alternatives considered

- **Record number only:** rejected because it cannot detect replacement,
  truncation before the record, blank-line changes, or content mutation.
- **Provider file identifier only:** rejected because providers may preserve an
  identifier while content changes and because it does not bind the acknowledged
  record position.
- **HTTP Range plus byte offset:** rejected as the default because range support,
  content codings, and stable validators are not guaranteed across compatible
  gateways; it also skips prefix revalidation.
- **Package-owned checkpoint table:** deferred because host transaction and
  tenant boundaries differ, and adding a mandatory schema would weaken
  standalone embeddability.
- **HMAC or signature:** rejected as a package default because the package does
  not own a checkpoint-signing key or provider attestation contract. A host may
  wrap the serialized checkpoint in its own authenticated envelope.
- **Full-stream manifest before delivery:** deferred because it requires a second
  complete pass or provider-owned stable digest and changes time-to-first-record.
  Hosts needing suffix immutability may add this stronger boundary externally.

## Verification

Deterministic tests prove chunk independence, result-before-error ordering,
resume without acknowledged-record replay, final-checkpoint completion,
result-prefix binding for error-file checkpoints, mutation and truncation at or
before the checkpoint before delivery, changed file identity rejection, strict
non-coercive local validation before credentials or network access, exact
response cleanup, newline and blank-line framing sensitivity, an explicit
unseen-suffix limitation, Python 3.10/3.12/3.14 compatibility, and 100%
production statement, branch, and public-docstring coverage.
