# Checkpoint audit snapshot manifest assurance record

## Scope

This record documents the bounded deterministic manifest used to identify one
snapshot-stable traversal of retained checkpoint accepted-save audit events. It
supplements the append-only audit trail and bounded keyset-pagination controls;
it does not replace row-level security, mutation rejection, separately governed
retention, or host authorization.

The commercial objective is narrow: an operator or acquiring reviewer should be
able to identify the exact contents of one stable audit traversal without
materializing an unbounded history in package memory and without mistaking a
pagination cursor for completeness or integrity evidence.

## Transaction and resource boundary

`build_audit_snapshot_manifest_in_transaction()` first requires one **active
PostgreSQL transaction** owned by the caller. The runtime uses Psycopg 3
`ConnectionInfo.transaction_status` and accepts only libpq `INTRANS` before it
issues any manifest-owned transaction-characteristic probe or audit page query.
Missing connection metadata, `IDLE`, `ACTIVE`, `INERROR`, `UNKNOWN`, and malformed
status evidence fail closed.

After active-transaction evidence succeeds, `SHOW transaction_isolation` must be
`repeatable read` or `serializable`, and `SHOW transaction_read_only` must be
`on`. PostgreSQL `READ COMMITTED` takes a fresh snapshot for each command, so a
multi-page digest under that isolation level could combine rows that never
belonged to one database snapshot. A read-write stable transaction is also
insufficient for retained-evidence identity because a transaction can observe its
own uncommitted writes. Without a **read-only** gate, a caller could insert an
accepted-save audit row, include it in a manifest, export that manifest, and then
roll back so the identified row was never durably retained. The package therefore
rejects `READ COMMITTED`, read-write transactions, malformed isolation or read-
only evidence, and unknown modes before page traversal.

A session-level isolation default is not enough. **autocommit** is rejected even
when `default_transaction_isolation` advertises `REPEATABLE READ`, because without
one active PostgreSQL transaction successive page statements can execute in
separate transactions and therefore separate snapshots. The host must begin a
read-only stable transaction and select its characteristics before its first
query. The package does not begin, commit, roll back, or change a caller-owned
transaction, isolation level, or read-only mode.

Traversal reuses the exact tenant-qualified keyset page API. `page_size` remains
a strict integer from 1 through 1,000 and `max_events` is a strict integer from 1
through 100,000. Package-owned memory is bounded to one page plus fixed digest
state. If another continuation remains when `max_events` has been consumed, the
operation fails closed instead of returning a digest for a silently truncated
history.

## Digest compatibility contract

Manifest schema version 1 uses SHA-256 over domain-separated, explicitly length-
framed UTF-8 values. Each frame contains a four-byte unsigned big-endian label
length, the label bytes, an eight-byte unsigned big-endian value length, and the
value bytes. The header binds the domain plus the trusted tenant, consumer,
endpoint, and batch key.

Every retained event is then bound in strict newest-first order. The digest
includes `checkpoint_audit_event_id`, tenant scope, consumer name, endpoint
alias, remote batch ID, action, schema version, file kind, file ID, physical and
logical positions, record count, prefix SHA-256, and `recorded_at`. Timestamps are
normalized to UTC and rendered with fixed microsecond precision and a trailing
`Z`. A final frame binds the event count plus newest and oldest event identities.
Page boundaries are deliberately excluded, so two valid page sizes produce the
same digest for the same stable snapshot.

A permanent compatibility vector locks the version-1 framing. The reviewed
single-event fixture has digest:

```text
2bc17add90c354f1ed53efc3031dff567cfb8cddd6e15f6577a024f48a026b96
```

Changing any version-1 framing rule incompatibly requires a new manifest schema
version rather than reinterpretation of retained evidence.

`CheckpointAuditSnapshotManifest` also revalidates its own public evidence. An
empty manifest has no event identities; a one-event manifest has the same newest
and oldest identity; and a multi-event manifest requires a strictly descending
identity range. The digest must be exactly 64 lowercase hexadecimal characters.

## Security and privacy boundary

FIPS 180-4 specifies SHA-256 as part of the Secure Hash Standard. In this feature,
SHA-256 is used only for deterministic content identity and change detection. An
unkeyed digest is not a MAC, digital signature, credential, authorization check,
trusted timestamp, delivery receipt, provenance statement, or non-repudiation
mechanism.

NIST SP 800-53 Rev. 5 AU-9 requires protection of audit information against
unauthorized access, modification, and deletion. The existing checkpoint audit
table uses forced row-level security and mutation rejection for ordinary
application roles. PostgreSQL owners, superusers, `BYPASSRLS` roles, disabled
triggers, and physical database administrators remain outside that assurance
boundary. An administrator capable of rewriting both retained rows and an
unkeyed digest can construct a different internally consistent pair.

Deployments that require administrator-independent preservation should export the
events and manifest into separately governed immutable or write-once storage.
Where authenticity is required, the host may sign or authenticate the exported
manifest under its own reviewed key-management boundary. Destination credentials,
legal hold, retention periods, disposal, delivery receipts, external signing,
and reconciliation remain host/operator responsibilities.

The manifest contains only the structured audit fields already retained by the
package. It does not add prompts, provider bodies, model output, credentials,
DSNs, transport headers, or arbitrary exception text.

## Operational workflow

1. Select the tenant, consumer, endpoint, and batch key only after host
   authentication and authorization.
2. Begin one active **read-only** PostgreSQL transaction with `REPEATABLE READ` or
   `SERIALIZABLE` before its first query. Do not use autocommit for a snapshot
   manifest, even if the session default is `REPEATABLE READ`, and do not perform
   data modification in the manifest transaction.
3. Call `build_audit_snapshot_manifest_in_transaction()` with a reviewed
   `page_size` and `max_events` budget. An overflow is an operational condition to
   handle explicitly, not permission to truncate evidence silently.
4. Export the corresponding retained events and the returned manifest under the
   same stable read-only transaction when the destination workflow requires one
   coherent database snapshot.
5. Persist destination-side immutable retention evidence and delivery receipts as
   required. Sign or authenticate the manifest externally when the assurance
   requirement needs producer authenticity.
6. Run later reconciliation as a separate pass for events committed after the
   exported database snapshot.

## Rollback

This feature introduces no database migration or retained-data transformation.
Code rollback removes the manifest API, compatibility tests, and documentation
only. Existing audit rows and pagination behavior remain unchanged.

Do not delete audit evidence as a feature rollback. The existing audit rollback
migration continues to refuse removal while retained events exist. Any exported
manifest or signed external evidence remains subject to the host's retention and
legal-hold policy.

The read-only manifest gate specifically prevents a different rollback hazard:
manifest construction cannot include caller-local audit rows created in the same
transaction and then lost on caller rollback. This is an evidence-validity
boundary, not a substitute for durable external retention.

## Verification contract

Permanent deterministic tests cover:

- strict non-coercive `page_size` and `max_events` bounds;
- strict public manifest schema, digest, and identity-range validation;
- rejection unless `ConnectionInfo.transaction_status` proves `INTRANS`;
- rejection of autocommit even with a `REPEATABLE READ` session default;
- rejection of active `READ COMMITTED` and malformed isolation evidence;
- rejection of active read-write transactions and malformed read-only evidence;
- acceptance of active read-only `REPEATABLE READ` and `SERIALIZABLE`;
- incremental keyset traversal without whole-history materialization;
- fail-closed traversal overflow instead of silent truncation;
- digest sensitivity to retained event fields;
- page-partition invariance for one stable snapshot;
- the fixed schema-version-1 digest compatibility vector; and
- public package-root exports.

The live least-privilege PostgreSQL test establishes an active read-only
`REPEATABLE READ` view, commits a newer accepted-save event from another
connection, and proves that manifests built with different page sizes keep the
same earlier event set and digest. It separately verifies active `READ COMMITTED`
rejection and autocommit rejection under a `REPEATABLE READ` session default. The
repository CI explicitly executes this integration test alongside the existing
checkpoint-audit and migration-operator PostgreSQL tests.

Final merge evidence is valid only after the stacked dependency chain has
integrated and fresh exact-head/exact-base quality, security, coverage,
packaging, provenance, release-acceptance, branch-protection, required-check, and
independent-review gates succeed on the protected integration head.

## APA 7 references

Joint Task Force. (2020, updated 2025). *Security and privacy controls for
information systems and organizations* (NIST Special Publication 800-53,
Revision 5, Release 5.2.0). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

National Institute of Standards and Technology. (2015). *Secure Hash Standard
(SHS)* (Federal Information Processing Standards Publication 180-4). U.S.
Department of Commerce. https://doi.org/10.6028/NIST.FIPS.180-4

PostgreSQL Global Development Group. (2026). *BEGIN*. PostgreSQL 18
documentation. https://www.postgresql.org/docs/18/sql-begin.html

PostgreSQL Global Development Group. (2026). *Transaction isolation*. PostgreSQL
18 documentation. https://www.postgresql.org/docs/18/transaction-iso.html

PostgreSQL Global Development Group. (2026). *SET TRANSACTION*. PostgreSQL 18
documentation. https://www.postgresql.org/docs/18/sql-set-transaction.html

PostgreSQL Global Development Group. (2026). *Client connection defaults*.
PostgreSQL 18 documentation.
https://www.postgresql.org/docs/18/runtime-config-client.html

Psycopg Team. (2026). *ConnectionInfo.transaction_status*. Psycopg 3 API
documentation.
https://www.psycopg.org/psycopg3/docs/api/objects.html#psycopg.ConnectionInfo.transaction_status

This assurance record uses APA 7 reference formatting for the authoritative
sources that define the implemented transaction, audit-protection, and digest
boundaries.
