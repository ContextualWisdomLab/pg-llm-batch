# Checkpoint migration operator assurance record

## Assurance objective

Provide one bounded operator workflow for existing PostgreSQL volumes that loads,
identifies, serializes, atomically applies, and reports the package's durable
checkpoint and checkpoint accepted-save audit migrations without changing the
backward-compatible core `init-db` command.

The command is `init-checkpoint-storage`. Its exact ordered inputs are
`0007_result_stream_checkpoints` and
`0008_result_checkpoint_audit_events`.

## Control boundary

The package controls:

- a 1 MiB maximum for each canonical migration file, enforced with a read request
  of at most the limit plus one detection byte;
- strict UTF-8 decoding and SHA-256 identity evidence before database access;
- exact 0007 then 0008 ordering;
- one fixed two-key transaction-level `pg_advisory_xact_lock`;
- one PostgreSQL transaction and one commit after both statements succeed;
- rollback of migration 0007 when migration 0008 fails in the same invocation;
- bounded success output containing only migration identifier, byte count, and
  SHA-256; and
- preservation of the existing `init-db` and separate-helper interfaces.

The package does not control administrator behavior, arbitrary SQL clients,
backup policy, database clocks, replication, credential issuance, operating
system access, or organizational change approval. A PostgreSQL owner,
superuser, administrator, or client that does not obtain the same advisory lock
can execute schema changes outside this cooperative boundary.

SHA-256 identifies the exact loaded bytes for deterministic change comparison. It
is not a signature, authenticated provenance, remote attestation, code-signing
claim, publication authority, or integrated-release approval.

## Transaction semantics

PostgreSQL transaction blocks group statements into one all-or-nothing unit.
`init-checkpoint-storage` loads both files before calling psycopg, then opens one
connection, obtains `pg_advisory_xact_lock`, executes
`0007_result_stream_checkpoints`, executes
`0008_result_checkpoint_audit_events`, and issues one commit. An exception before
that commit leaves the connection context through its failure path, so PostgreSQL
rolls back the transaction and releases the transaction-level lock.

The lock keys are the reviewed signed 32-bit values for ASCII namespaces `PGLM`
and `BATH`. The two-key API reduces accidental collision with unrelated
application advisory locks while remaining constant across standalone and modular
MSA deployments.

Transaction-level advisory locks wait for conflicting holders and release
automatically at transaction end. They avoid stale lock rows and a new migration
ledger table. They coordinate only cooperating invocations; they are not an
authorization mechanism.

## Input and memory safety

Each file is opened in binary mode and read once with
`MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES + 1`. This establishes a strict package-
owned memory ceiling while still detecting one byte beyond the 1 MiB contract.
Empty, oversized, unreadable, or invalid UTF-8 files fail before database access.

The loaded SQL text remains private. The public immutable
`CheckpointSchemaMigration` exposes only:

- `migration_id` from the configured ordered plan;
- positive `byte_count` within the 1 MiB limit; and
- lowercase 64-character hexadecimal `sha256`.

The CLI serializes these fields with a fixed schema version only after successful
commit. It never emits the DSN, password, SQL body, tenant, checkpoint record,
provider response, audit row, or raw database exception.

## Compatibility and modularity

`init-db` continues to apply only the core batch schema. The existing
`apply_result_checkpoint_schema()` and
`apply_result_checkpoint_audit_schema()` functions retain their independent
transaction behavior for hosts that intentionally own orchestration.

`apply_checkpoint_schema_migrations()` is independently usable and does not
require `naruon`, `contextual-orchestrator`, a model provider, or an LLM key.
CWL hosts may store returned descriptors in their deployment change record but
must not reinterpret them as tenant identity or release provenance.

Fresh Docker data directories keep their ordered initialization scripts. Docker
entrypoint initialization is not an upgrade mechanism for existing PostgreSQL
volumes, which use the explicit operator command.

## Deterministic verification matrix

- Public RED head `9aedff7a50270a81cd245771dbe7f649a31fe66f`:
  CI run `31149845743`, Python 3.10 job `92777048403`, failed collection because
  `CheckpointSchemaMigration` and the migration coordinator did not exist.
- Unit GREEN head `c2de384dd5a42a026f1c49d9eeec92c5bff3217f`:
  Python 3.14 unit tests passed; the quality job completed compilation, Ruff,
  100% public docstrings, 100% production line coverage, lock freshness, and
  package build before the next test-first commit superseded the run. Superseded
  workflow evidence is not final merge evidence.
- Bounded-read RED contract head `049e6aab513494b114fddfe2e0679dc1ff19e921`
  rejects `Path.read_bytes()` and any negative-size read. The implementation now
  reads at most 1 MiB plus one byte.
- Workflow RED contract head `6a7ac0125ea67ee60b88d41d3a6a9d56cf8cef75`
  requires the permanent PostgreSQL job to run both audit and migration operator
  integration suites.
- Unit tests prove immutable descriptors, strict non-coercive field validation,
  exact order/digests, empty/oversized/non-UTF-8 rejection, pre-connection input
  failure, one advisory lock, exact SQL order, one commit, and failure propagation
  without success evidence.
- Live PostgreSQL tests prove an invalid second migration rolls back the first and
  a concurrent worker has an ungranted advisory lock until the holder commits.
- CI contract tests bind the pinned PostgreSQL image, DSN, credential-free
  checkout, and exact integration command to the reviewed job rather than a
  repository-wide string search.
- Final acceptance requires fresh exact-head/current-base CI, security,
  dependency, packaging, migration, rollback, concurrency, container,
  reproducibility, review, and branch-protection evidence. Queued, pending,
  cancelled, skipped-required, absent, stale-head, stale-base, and synthetic-
  merge-only results are not success.

## Standards mapping

NIST SP 800-53 Rev. 5 CM-3 requires configuration changes to be controlled,
documented, and reviewed. CM-3(2) requires changes to be tested, validated, and
documented before finalization. The ordered plan, immutable SHA-256 descriptors,
live rollback/concurrency tests, operator guide, ADR, and exact-head CI evidence
support those objectives.

PostgreSQL 18 system administration documentation defines
`pg_advisory_xact_lock` as an exclusive transaction-level advisory lock that
waits when necessary and is released automatically at transaction end. The
PostgreSQL transaction tutorial explains that a transaction groups multiple
steps into one all-or-nothing operation, and the `ROLLBACK` reference states that
rollback discards all updates in the current transaction.

These references support coordination and atomicity, not administrator-proof
schema control. Least-privilege roles, restricted direct SQL, backups, and
separately governed release provenance remain necessary controls.

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
