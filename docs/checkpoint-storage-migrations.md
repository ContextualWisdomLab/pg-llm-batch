# Checkpoint storage migrations

## Purpose

`pg-llm-batch` keeps durable result checkpoints and accepted-save audit evidence
opt-in. Fresh bundled PostgreSQL data directories receive their schemas through
ordered container initialization, but **existing PostgreSQL volumes** need an
explicit upgrade action. The supported operator command is:

```bash
python -m pg_llm_batch init-checkpoint-storage \
  --dsn 'postgresql://operator@database/pg_llm_batch'
```

`init-db` remains the backward-compatible core-schema command. It does not
silently install checkpoint or audit tables. Hosts that intentionally control
separate transactions may continue to call `apply_result_checkpoint_schema()`
and `apply_result_checkpoint_audit_schema()` independently.

## What the command does

The operator performs one deterministic sequence:

```text
init-checkpoint-storage
    ├─ bounded read + UTF-8 validation + SHA-256 of
    │  0007_result_stream_checkpoints
    ├─ bounded read + UTF-8 validation + SHA-256 of
    │  0008_result_checkpoint_audit_events
    ├─ connect only after both files are valid
    ├─ SELECT pg_advisory_xact_lock(PGLM, BATH)
    ├─ execute 0007_result_stream_checkpoints
    ├─ execute 0008_result_checkpoint_audit_events
    └─ one commit, then bounded JSON evidence
```

Each canonical SQL file is read with a maximum request of 1 MiB plus one byte.
An empty file, a file larger than 1 MiB, invalid UTF-8, or an unreadable second
file fails **before database access**. This prevents migration 0007 from being
committed merely because migration 0008 could not be loaded.

Inside PostgreSQL, the command obtains the fixed two-key transaction-level
advisory lock with `pg_advisory_xact_lock`. Cooperating package operators using
the same command serialize. The lock is released automatically when the
transaction ends. It does not prevent a privileged administrator or unrelated
SQL client from changing schemas outside this package boundary.

Both migrations run in one transaction and the package issues one commit only
after migration 0008 succeeds. A lock failure or SQL failure in migration 0008
rolls back migration 0007 from the same invocation. The command never executes
rollback scripts, downgrades schemas, deletes checkpoints, or erases retained
audit evidence.

## Success output

After commit, the command prints one canonical JSON object:

```json
{
  "applied_migrations": [
    {
      "byte_count": 123,
      "migration_id": "0007_result_stream_checkpoints",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    },
    {
      "byte_count": 456,
      "migration_id": "0008_result_checkpoint_audit_events",
      "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    }
  ],
  "schema_version": 1
}
```

The exact values depend on the reviewed package bytes. Output never contains the
DSN, credentials, SQL text, tenant identity, checkpoint values, provider bodies,
or audit rows. SHA-256 is deterministic change-identification evidence for the
loaded migration bytes; it is **not a signature**, authenticated provenance,
publication authority, or remote attestation.

## Deployment procedure

1. Back up the target database under the host's normal recovery policy.
2. Confirm the package artifact and version approved for the environment.
3. Run `plan_checkpoint_schema_migrations()` in a read-only preparation step
   when a change record needs byte counts and digests before database access.
4. Run `init-checkpoint-storage` once with an operator identity authorized to
   create and alter the two package tables, policies, indexes, functions, and
   triggers.
5. Retain the canonical JSON with the deployment change record.
6. Run the command again in non-production rehearsal and upgrade tests to prove
   idempotency before rollout to additional environments.
7. Verify application roles remain `NOSUPERUSER NOBYPASSRLS` and receive only
   the least privileges documented for checkpoint and audit operations.

A failed command emits no success JSON. Preserve the original exception and
PostgreSQL logs under the host's restricted operator process; do not paste DSNs,
credentials, or unbounded SQL errors into public tickets.

## Modular use

The operator is standalone and has no dependency on `naruon` or
`contextual-orchestrator`. CWL hosts may call
`apply_checkpoint_schema_migrations()` during their own deployment workflow and
store the returned descriptors in a tenant-neutral change record. They must not
reinterpret the descriptors as tenant authorization or integrated-release
provenance.
