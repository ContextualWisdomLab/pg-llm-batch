# ADR 0012: Bounded checkpoint-audit snapshot manifests

- **Status:** Accepted for the stacked implementation
- **Date:** 2026-08-07
- **Decision owners:** ContextualWisdomLab
- **Depends on:** ADR 0009 and ADR 0011
- **Stack order:** Follows the bounded checkpoint-audit export pagination slice

## Context

ADR 0011 provides bounded keyset pagination for retained checkpoint audit events,
but a pagination cursor is only navigation state. It does not identify the
contents of one complete traversal, and package-owned page calls normally execute
under separate PostgreSQL `READ COMMITTED` transactions. A buyer or operator who
exports audit evidence therefore still needs a compact deterministic identity for
one database-snapshot-stable traversal without loading the entire retained audit
history into process memory.

The package must not misrepresent that identity as authentication, external
immutability, proof of delivery, non-repudiation, or administrator-proof tamper
evidence. Those properties require separately governed controls and, for
cryptographic authenticity, a secret key or private signing key outside this
package boundary.

## Decision

Add immutable public `CheckpointAuditSnapshotManifest` schema version 1 and the
caller-transaction method
`build_audit_snapshot_manifest_in_transaction()` on
`AuditedPostgresBatchResultCheckpointStore`.

The method is intentionally caller-transaction-only. It verifies
`SHOW transaction_isolation` and accepts only PostgreSQL `REPEATABLE READ` or
`SERIALIZABLE`. `READ COMMITTED`, malformed isolation evidence, and any weaker
or unknown mode fail closed. The package does not add a convenience wrapper that
silently changes transaction isolation because PostgreSQL requires isolation to
be selected before the first query or data-modification statement and because a
library must not rewrite host-owned transaction semantics implicitly.

Traversal reuses ADR 0011 keyset pages. `page_size` remains a strict integer from
1 through 1,000. `max_events` is a separate strict integer from 1 through 100,000.
The builder keeps only one bounded page plus fixed manifest state in package-owned
memory. If another continuation remains when `max_events` has been consumed, the
operation raises instead of silently describing a truncated history.

The schema-version-1 digest uses SHA-256 and a domain-separated, unambiguous
length-framed byte contract. The header binds the trusted tenant, consumer,
endpoint, and batch key. Every retained `CheckpointAuditEvent` field is then
bound in strict newest-first order, including database identity, action,
checkpoint coordinates, prefix digest, and `recorded_at`. Timestamps are
normalized to UTC with fixed microsecond precision before framing. A final frame
binds event count plus newest and oldest event identities. Page boundaries are
not included, so changing a valid page size cannot change the digest for the same
snapshot.

`CheckpointAuditSnapshotManifest` validates its own schema version, trusted key,
bounded count, event-identity range, and lowercase 64-hex-character digest. An
empty manifest has no event identities. A one-event manifest requires equal
newest and oldest identities. A multi-event manifest requires a strictly
descending identity range. A permanent known digest vector freezes schema
version 1 framing; an incompatible framing change requires a new schema version.

## Security and acquisition boundary

FIPS 180-4 standardizes SHA-256 as a secure hash algorithm. Here SHA-256 is used
only as deterministic content-identity and change-detection evidence. The digest
is not a MAC, signature, credential, authorization decision, trusted timestamp,
proof of delivery, or non-repudiation mechanism.

NIST SP 800-53 Rev. 5 AU-9 requires protection of audit information from
unauthorized access, modification, and deletion. The package continues to use
forced RLS and ordinary-role mutation rejection for the PostgreSQL audit table,
but database owners, superusers, `BYPASSRLS` roles, disabled triggers, and
physical database administrators remain outside that protection boundary. A host
that requires independently durable evidence should export the manifest and
retained events to separately governed immutable or write-once storage and may
sign or authenticate the exported manifest under its own key-management policy.

The feature introduces no database object, migration, provider credential, LLM
key, network exporter, background scheduler, or external retention destination.
It preserves standalone operation and can be embedded into CWL services without
requiring `contextual-orchestrator` or `naruon`.

## Alternatives rejected

### Hash each page independently

Rejected because page boundaries are operator tuning parameters. Independent page
hashes would make evidence identity depend on page size and would not provide one
compact identity for the complete snapshot traversal.

### Hash under READ COMMITTED

Rejected because PostgreSQL takes a new `READ COMMITTED` snapshot for each
statement. A multi-page digest could therefore describe rows that never belonged
to one database snapshot while still looking like one manifest.

### Materialize every event and hash afterward

Rejected because retained audit volume is not bounded by one interactive use.
The package's acquisition-readiness boundary requires bounded memory and explicit
resource ceilings.

### Implicitly set transaction isolation

Rejected because PostgreSQL does not permit changing isolation after the first
query or data-modification statement and because the caller owns the transaction.
The library verifies the required isolation instead of trying to repair a moving
transaction after the fact.

### Treat SHA-256 as authenticity evidence

Rejected because an unkeyed digest cannot prove who produced the evidence or
prevent an administrator capable of rewriting both data and digest from creating
a different internally consistent pair.

## Verification

Permanent deterministic tests cover strict manifest construction, strict bounded
limits, isolation evidence, empty/one/multi-event identity consistency,
incremental page traversal, overflow failure, retained-field sensitivity,
package-root exports, and a fixed schema-version-1 digest vector. The existing
100% production statement, branch, and public-docstring coverage gate remains
mandatory.

A live least-privilege PostgreSQL test establishes a `REPEATABLE READ` snapshot,
commits a newer accepted-save event from another connection, and proves that two
manifest builds with different page sizes retain the same earlier snapshot and
digest. The same live test verifies that PostgreSQL's default `READ COMMITTED`
is rejected. CI explicitly executes this integration test.

Final merge evidence is valid only after the full stack is integrated and fresh
quality, security, coverage, packaging, provenance, release-acceptance, branch-
protection, required-check, and independent-review gates succeed on the exact
protected head and exact current base.

## Consequences

Operators gain a bounded deterministic identity for one stable audit snapshot
without a schema migration or unbounded in-process accumulation. External
retention, receipts, legal hold, reconciliation, signing, authentication, key
management, and administrator-independent immutability remain host/operator
responsibilities. Version `0.1.0` and publication state remain unchanged.
