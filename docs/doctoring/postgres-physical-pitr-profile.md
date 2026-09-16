# PostgreSQL physical and PITR recovery profile

This record is the operator contract for
`bind_postgres_physical_recovery_profile()`. Use it before you claim that a
deployment can recover through WAL replay. The function binds evidence. It does
not run `pg_basebackup`, `restore_command`, or `pg_restore`.

## What to do next

1. Create an isolated recovery target first. Pass
   `isolated_target_prepared=True` only after that target exists. The boolean
   is your assertion, not package proof of isolation.
2. Choose `backup_method="physical"` only for a crash-consistent base backup
   whose recovery target kind is `immediate`. `wal_archive_required=False`
   means you are not claiming a continuous WAL archive. It does not mean the
   base backup can omit backup-internal WAL. Keep the WAL generated during
   the backup (`pg_basebackup -X stream` or `-X fetch`) with the backup.
3. Choose `backup_method="pitr"` only when a continuous WAL archive is already
   being written and you can restore to a time, transaction identifier, named
   restore point, LSN, or immediate consistent state. `immediate` on a `pitr`
   profile is end-of-backup consistency, not replay to the end of the archive.
   Replay-to-end-of-archive is the absence of a `recovery_target*` setting, not
   a kind this binder records.
4. Record deployer-selected `rpo_seconds` and `rto_seconds` when your
   organization has those objectives. Read `package_capability_claim=false` as
   a hard rule: this package did not meet those numbers for you.
5. Keep Fernet keys, TLS private material, host configuration, and provider
   files outside database and WAL custody unless a separately reviewed adapter
   owns them.
6. After you bind the profile, run the actual base backup and WAL restore
   outside this seam, then prove schema, tenant/RLS, checkpoint, and lifecycle
   usability on the isolated target.

## Recovery-target configuration observation

PR #299 adds a bounded read-only handoff between deployer-owned target
configuration and later replay/readiness evidence. Until that PR and this
owner-path successor are normally integrated, treat this section as the
branch-local operator contract rather than protected or released authority.

After the recovery target has been configured and PostgreSQL is already running
in recovery on an isolated target, call
`observe_postgres_recovery_target_configuration()` with the caller-owned open
connection and the exact reviewed `PostgresPitrRecoveryTarget`. The observer
reads only these effective `pg_settings` values:

- `recovery_target`;
- `recovery_target_action`;
- `recovery_target_inclusive`;
- `recovery_target_lsn`;
- `recovery_target_name`;
- `recovery_target_time`;
- `recovery_target_timeline`;
- `recovery_target_xid`.

PostgreSQL 18 defaults `recovery_target_inclusive` to `on`. When the reviewed
target omits an inclusion edge (`name` or `immediate`), accept the observation
only if the effective setting is still `on`; the observer intentionally does not
treat an empty value as equivalent. Time, XID, and LSN targets retain their
explicit reviewed inclusion edge.

The same fixed query also calls `pg_is_in_recovery()`. PostgreSQL documents that
function as true while recovery remains in progress. The query requests one row
beyond the eight-setting budget so an unexpected result set fails closed rather
than being materialized without a bound.

Treat any malformed row, duplicate or unknown setting name, oversized setting
text, `pending_restart=true`, inactive recovery, or mismatch with the reviewed
target as a failed observation. A `pending_restart` value means the effective
runtime configuration is not yet the requested configuration, so do not accept
that target as ready for later replay evidence.

The caller owns connection setup, authentication, authorization, isolation and
timeout policy. Do not open a long-lived database transaction or retain a lock
while performing backup, WAL replay, provider, model, or other network work.
The observation seam does not issue `SET`, `ALTER SYSTEM`, configuration-file
writes, or other hidden connection-state changes.

Successful evidence is content-free live-object provenance. Do not add DSNs,
credentials, target values, restore-point names, filesystem paths, WAL contents,
or dynamic database exception text to the evidence or logs.

Most importantly, a successful configuration observation is **not** recovery
completion. It does not create `recovery.signal`, supply `restore_command`,
replay or validate WAL, prove archive completeness or timeline ancestry, prove
that the recovery target was reached, pause or promote recovery, prove
application readiness, or establish achieved RPO/RTO, HA/DR, CSAP, SOC 2, or
certification claims. Use the dedicated replay and readiness evidence seams for
those later decisions.

## Time-flow boundary

PostgreSQL point-in-time recovery is a time-flow control. Kinds `time`,
`xid`, `name`, and `lsn` are accepted only on a `pitr` profile with
`wal_archive_required=True`. A physical profile cannot borrow those kinds even
when WAL is being archived. That prevents labeling a crash-consistent restore
as a point-in-time restore.

## What this slice does not prove

The binder does not execute physical backup, WAL archive, or replay. The
configuration observer only checks bounded effective recovery-target settings
on an already-connected recovery target. Neither proves schema/RLS/constraint/
extension parity, target isolation, target attainment, universal RPO/RTO, high
availability, disaster recovery, CSAP, or SOC 2 readiness. Those remain issue
#204 and deployment-specific evidence. Canonical CHANGELOG and README ownership
for the broader recovery program stays with the documentation and
restore-executor writers.

## Verification

Confirm on the exact current head that:

- a PostgreSQL 18 `pitr` + `time` profile round-trips without a capability claim;
- `pitr` without a WAL archive fails closed;
- point-in-time kinds on a `physical` method fail closed;
- `isolated_target_prepared=False` fails closed;
- exact-type and hostile-subclass metadata fail closed;
- parse rejects lone UTF-8 surrogates with the typed profile JSON error;
- parse rejects duplicate keys, unknown keys, and a true capability claim;
- both operator documents name all eight observed recovery-target settings and
  `pg_is_in_recovery()`;
- both documents preserve PostgreSQL's `recovery_target_inclusive=on` default
  when the reviewed target has no inclusion edge;
- both documents preserve the read-only, bounded, fail-closed and content-free
  observation boundary; and
- production statement and branch coverage and public docstrings remain 100%.

## References

International Organization for Standardization. (2022). *Information security,
cybersecurity and privacy protection — Information security management systems
— Requirements* (ISO/IEC 27001:2022). Control A.8.13 requires information
backup; this package records bounded recovery evidence, not a certified ISMS.

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST Special
Publication 800-34 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-34r1

The PostgreSQL Global Development Group. (2026). *Backup and restore*.
PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/backup.html

The PostgreSQL Global Development Group. (2026). *Continuous archiving and
point-in-time recovery (PITR)*. PostgreSQL 18 documentation.
https://www.postgresql.org/docs/18/continuous-archiving.html

The PostgreSQL Global Development Group. (2026). *Write ahead log*. PostgreSQL
18 documentation. https://www.postgresql.org/docs/18/runtime-config-wal.html

The PostgreSQL Global Development Group. (2026). *pg_basebackup*. PostgreSQL 18
documentation. https://www.postgresql.org/docs/18/app-pgbasebackup.html

The PostgreSQL Global Development Group. (2026). *pg_settings*. PostgreSQL 18
documentation.
https://www.postgresql.org/docs/18/view-pg-settings.html

The PostgreSQL Global Development Group. (2026). *System administration
functions*. PostgreSQL 18 documentation.
https://www.postgresql.org/docs/18/functions-admin.html
