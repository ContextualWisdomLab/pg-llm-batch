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
   whose recovery target kind is `immediate`.
3. Choose `backup_method="pitr"` only when a WAL archive is already being
   written and you can restore to a time, transaction identifier, named restore
   point, LSN, or immediate consistent state.
4. Record deployer-selected `rpo_seconds` and `rto_seconds` when your
   organization has those objectives. Read `package_capability_claim=false` as
   a hard rule: this package did not meet those numbers for you.
5. Keep Fernet keys, TLS private material, host configuration, and provider
   files outside database and WAL custody unless a separately reviewed adapter
   owns them.
6. After you bind the profile, run the actual base backup and WAL restore
   outside this seam, then prove schema, tenant/RLS, checkpoint, and lifecycle
   usability on the isolated target.

## Time-flow boundary

PostgreSQL point-in-time recovery is a time-flow control. Kinds `time`,
`xid`, `name`, and `lsn` are accepted only on a `pitr` profile with
`wal_archive_required=True`. A physical profile cannot borrow those kinds even
when WAL is being archived. That prevents labeling a crash-consistent restore
as a point-in-time restore.

## What this slice does not prove

This binder does not execute physical backup, WAL archive, or replay. It does
not prove schema/RLS/constraint/extension parity, target isolation, universal
RPO/RTO, high availability, disaster recovery, CSAP, or SOC 2 readiness. Those
remain issue #204 and deployment-specific evidence. Canonical CHANGELOG and
README ownership for the broader recovery program stays with the documentation
and restore-executor writers.

## Verification

Confirm on the exact current head that:

- a PostgreSQL 18 `pitr` + `time` profile round-trips without a capability claim;
- `pitr` without a WAL archive fails closed;
- point-in-time kinds on a `physical` method fail closed;
- `isolated_target_prepared=False` fails closed;
- exact-type and hostile-subclass metadata fail closed;
- parse rejects duplicate keys, unknown keys, and a true capability claim;
- production statement and branch coverage and public docstrings remain 100%.

## References

International Organization for Standardization. (2022). *Information security,
cybersecurity and privacy protection — Information security management systems
— Requirements* (ISO/IEC 27001:2022). Control A.8.13 requires information
backup; this package records a bounded physical/PITR profile, not a certified
ISMS.

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST Special
Publication 800-34 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-34r1

The PostgreSQL Global Development Group. (2026). *Backup and restore*.
PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/backup.html

The PostgreSQL Global Development Group. (2026). *Continuous archiving and
point-in-time recovery (PITR)*. PostgreSQL 18 documentation.
https://www.postgresql.org/docs/18/continuous-archiving.html

The PostgreSQL Global Development Group. (2026). *pg_basebackup*. PostgreSQL 18
documentation. https://www.postgresql.org/docs/18/app-pgbasebackup.html
