# ADR 0010: Atomic checkpoint schema operator

- **Status:** Accepted
- **Date:** 2026-08-07
- **Decision owners:** ContextualWisdomLab maintainers

## Context

The durable checkpoint migration `0007_result_stream_checkpoints` and the
accepted-save audit migration `0008_result_checkpoint_audit_events` are ordered
and individually idempotent. Existing public helpers apply each migration through
a separate connection and commit. That separation is intentionally compatible
with hosts that own upgrade orchestration, but it leaves a buyer-visible operator
gap: a routine existing-volume upgrade can partially install checkpoint schema
when the audit migration is missing, unreadable, malformed, or fails after the
first helper commits.

Docker entrypoint initialization is suitable only for a fresh data directory and
must not be represented as an upgrade mechanism for existing PostgreSQL volumes.
The core `init-db` command also cannot silently gain optional checkpoint objects
without breaking the established standalone compatibility boundary.

## Decision

Add the explicit opt-in command `init-checkpoint-storage` and public coordinator
`apply_checkpoint_schema_migrations()`.

The coordinator performs these steps in order:

1. bounded-read, validate as strict UTF-8, count, and SHA-256 identify
   `0007_result_stream_checkpoints`;
2. bounded-read, validate as strict UTF-8, count, and SHA-256 identify
   `0008_result_checkpoint_audit_events`;
3. connect only after both canonical files pass the 1 MiB bound;
4. obtain the fixed two-key transaction-level advisory lock through
   `pg_advisory_xact_lock`;
5. execute migration 0007 and then migration 0008 in one transaction;
6. issue one commit; and
7. return only immutable migration identifiers, byte counts, and SHA-256 values.

The JSON emitted by the CLI appears only after successful commit. It excludes
DSNs, credentials, SQL bodies, tenants, checkpoint values, provider payloads,
audit rows, and raw exception text. SHA-256 is change-identification evidence,
not a signature, provenance statement, attestation, or release authorization.

`init-db`, `apply_result_checkpoint_schema()`, and
`apply_result_checkpoint_audit_schema()` remain source compatible. No migration
ledger table, downgrade operation, destructive rollback, version bump, or release
publication is introduced.

## Rationale

PostgreSQL transaction-level advisory locking coordinates cooperating operator
invocations without creating another database object or lifecycle table. The lock
waits rather than treating routine concurrent deployment as a fatal race and is
released automatically on commit, rollback, process failure, or connection
termination. One transaction makes the ordered pair all-or-nothing: a failure in
`0008_result_checkpoint_audit_events` rolls back changes made by
`0007_result_stream_checkpoints` during the same command.

Loading both files before database access addresses a different failure class
than transaction rollback. A missing or oversized second file is a local package
input failure and should not open a database transaction or acquire a lock.
Bounded reads prevent a replaced package file from causing unbounded library-owned
memory use before the size decision.

A migration ledger was rejected for this slice. The two canonical migrations are
already idempotent, and a ledger would create a second mutable state authority,
new recovery and tamper questions, and compatibility obligations without being
necessary for ordered atomic application.

## Consequences

### Positive

- Existing PostgreSQL volumes receive a beginner-readable, deterministic upgrade
  command.
- Concurrent package operators serialize on one reviewed lock namespace.
- The two optional schemas cannot be partially committed by this command.
- Change records can retain bounded migration identity evidence without secrets
  or SQL bodies.
- Standalone and modular MSA hosts can adopt the coordinator without requiring
  `naruon` or `contextual-orchestrator`.

### Limitations

- `pg_advisory_xact_lock` coordinates only clients that use the same lock. A
  privileged administrator or unrelated SQL process can still alter schema
  outside this boundary.
- SHA-256 identifies bytes but does not authenticate their origin.
- Database roles, backups, maintenance windows, replication, and organization
  change approval remain operator responsibilities.
- The command upgrades forward only. It does not delete retained checkpoint or
  audit evidence and does not execute packaged rollback SQL.

## Verification

Deterministic tests cover descriptor validation, canonical order, bounded reads,
pre-connection failure, one lock, one transaction, one commit, canonical body-free
JSON, and unchanged `init-db` behavior. Live PostgreSQL tests prove that invalid
migration 0008 rolls back migration 0007 and that a concurrent invocation waits
on the transaction-level advisory lock before completing. CI retains read-only
repository permissions and credential-free checkout.

## Standards and references

NIST SP 800-53 Rev. 5 CM-3 and CM-3(2) motivate controlled, tested, validated,
and documented configuration changes. PostgreSQL 18 documents transaction blocks
as all-or-nothing, `ROLLBACK` as discarding the transaction's updates, and
`pg_advisory_xact_lock` as an exclusive transaction-level lock released at
transaction end.

`init-checkpoint-storage`, `0007_result_stream_checkpoints`,
`0008_result_checkpoint_audit_events`, `pg_advisory_xact_lock`, and SHA-256 are
therefore part of the authoritative migration contract.
