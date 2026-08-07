# Checkpoint Migration Operator Design

## Status

Approved bounded vertical slice for implementation on the stacked branch
`agent/checkpoint-migration-operator`. The exact prerequisite is PR #62 head
`2820aa36d8dedf7d89d1b745e5728acf3b913d2b`.

## Buyer-visible gap

The package exposes durable checkpoint and checkpoint-audit migrations, but an
operator must currently know and call two independent Python helpers in the
correct order. Each helper opens and commits its own transaction. Existing
PostgreSQL volumes therefore lack one package-owned command that:

- validates both canonical migration inputs before database mutation;
- serializes concurrent migration attempts;
- applies durable checkpoint schema before checkpoint-audit schema;
- commits the ordered pair atomically or rolls both back;
- returns bounded machine-readable migration identity evidence; and
- preserves the existing opt-in boundary instead of silently changing
  `init-db`.

This is an acquisition-readiness gap because migration ordering and rollback
are currently procedural knowledge rather than a deterministic operator
contract.

## Decision

Add a focused `pg_llm_batch.checkpoint_migrations` module and the explicit CLI
command `init-checkpoint-storage`.

The module will load the canonical package migrations
`0007_result_stream_checkpoints.sql` and
`0008_result_checkpoint_audit_events.sql` in that exact order before opening a
database connection. Each file is non-empty, bounded to 1 MiB, and represented
by an immutable descriptor containing only a stable migration identifier,
byte count, and SHA-256 digest.

Application will use one PostgreSQL connection and one transaction. Before the
first migration statement, it obtains the fixed two-key transaction-level
advisory lock:

```sql
SELECT pg_advisory_xact_lock(%s, %s)
```

The reviewed keys are package constants derived from the stable ASCII namespace
`PGLM` and operation `BATH`. Transaction-level advisory locks wait for a
competing holder and release automatically at transaction end. The operator
then executes migration 0007 followed by 0008 and commits once. Any load,
connection, lock, or SQL failure propagates before a success report; PostgreSQL
rolls the transaction back and releases the lock.

The CLI emits one canonical JSON object only after commit:

```json
{
  "schema_version": 1,
  "applied_migrations": [
    {
      "migration_id": "0007_result_stream_checkpoints",
      "byte_count": 123,
      "sha256": "..."
    },
    {
      "migration_id": "0008_result_checkpoint_audit_events",
      "byte_count": 456,
      "sha256": "..."
    }
  ]
}
```

The report excludes the DSN, credentials, SQL text, database exception text,
tenant identifiers, checkpoint values, and audit rows. SHA-256 is deterministic
change-identification evidence for the applied package bytes, not a signature or
remote attestation.

## Compatibility boundary

- `init-db` remains unchanged and continues to apply only the existing core
  schema.
- Existing public `apply_result_checkpoint_schema()` and
  `apply_result_checkpoint_audit_schema()` helpers remain source compatible for
  hosts that intentionally manage separate transactions.
- The new coordinator is opt-in and independently usable without `naruon` or
  `contextual-orchestrator`.
- Fresh Docker data directories keep their existing ordered entrypoint
  migrations. Existing volumes use the explicit operator command.
- No migration ledger table is introduced. The canonical migrations are already
  idempotent; adding a second state authority would increase recovery and
  tamper-analysis scope without solving the bounded operator gap.

## Failure and recovery contract

- Both migration files are loaded and hashed before database access. A missing,
  empty, unreadable, or oversized second file cannot leave migration 0007
  partially applied.
- The advisory lock is transaction-scoped. Process failure, rollback, or
  connection loss releases it through PostgreSQL transaction termination.
- A failure in migration 0008 rolls back migration 0007 from the same operator
  invocation.
- A successful rerun is supported by the existing idempotent SQL and emits the
  same ordered identity evidence for unchanged package bytes.
- The command does not downgrade, delete retained checkpoint/audit evidence, or
  invoke rollback scripts.

## Verification design

Strict RED → GREEN tests will prove:

1. canonical order, identifiers, byte counts, and SHA-256 values;
2. non-empty and 1 MiB input bounds before database connection;
3. one connection, one transaction-level advisory lock, exact SQL order, and
   one commit;
4. no success report or commit after the second migration fails;
5. stable public exports and a canonical body-free CLI report;
6. live PostgreSQL all-or-nothing behavior with an intentionally invalid second
   migration;
7. live concurrent invocations serialize on the same advisory lock;
8. unchanged `init-db` behavior and separate-helper compatibility; and
9. synchronized README, AGENTS, CLAUDE, architecture, ADR, doctoring, operator,
   and changelog contracts with 100% production statement, branch, and public
   docstring coverage.

## Standards basis

NIST SP 800-53 Rev. 5 CM-3 requires controlled, documented, and reviewed system
changes, while CM-3(2) requires testing, validation, and documentation before
finalization. PostgreSQL 18 documents transaction blocks as all-or-nothing and
`pg_advisory_xact_lock` as an exclusive transaction-level advisory lock that is
released automatically at transaction end. This design uses those controls to
turn two migration scripts into one deterministic, testable operator action.

## APA 7 references

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Revision 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

PostgreSQL Global Development Group. (2026). *System administration functions*
(PostgreSQL 18 documentation).
https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026). *Transactions* (PostgreSQL 18
documentation). https://www.postgresql.org/docs/18/tutorial-transactions.html

PostgreSQL Global Development Group. (2026). *ROLLBACK* (PostgreSQL 18
documentation). https://www.postgresql.org/docs/18/sql-rollback.html
