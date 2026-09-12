# PostgreSQL logical restore execution

This record is the operator contract for `restore_postgres_logical_backup()`.
Use it before you point `pg_restore` at a recovery target. The function is a
bounded executor, not a complete backup, PITR, or certification program.

## What to do next

1. Restore only into an isolated libpq service that you already created for
   recovery. Do not aim this executor at a live production service name.
2. Pass `source_superusers_trusted=True` only after you have independently
   proven the archive came from trusted source superusers. The boolean is your
   assertion, not package proof of provenance, ownership, or privilege safety.
3. Keep Fernet keys, TLS private material, host configuration, and provider
   files outside the database archive unless a separately reviewed adapter owns
   them. A successful SQL restore does not reconstruct those secrets.
4. If restore returns a metadata-changed error after `pg_restore` exits zero,
   treat the target as unsafe. The SQL transaction may already have committed.
   Do not retry blindly into the same target.
5. After a successful call, run your isolated acceptance drill: schema,
   extension, tenant/RLS, constraint, checkpoint, and lifecycle usability.
   Exit status zero is not that drill.

## Direct SQL and rollback boundary

The executor invokes `pg_restore --single-transaction --exit-on-error
--dbname=service=<validated-service-name>`. That is a direct SQL restore, not a
script renderer. Timeout or execution failure is intended to abort the one
restore transaction so a partial package restore is not committed. The service
name is a connection selector, not an authorization or isolation proof.

Only `PGPASSWORD`, `PGPASSFILE`, and `PGSERVICEFILE` may be inherited. Ambient
`PGHOST`, `PGDATABASE`, `PGOPTIONS`, and `PGSSLMODE` values cannot silently
redirect or weaken the target session. Archive paths and credentials never enter
process arguments. Diagnostics stay content-free.

## Custom-format seek contract

PostgreSQL custom-format archives are designed so `pg_restore` can reorder
archived items and must use a regular file rather than a pipe when it needs
random access. The child therefore seeks to the table of contents and data
blocks. A successful restore is **not** required to leave the caller descriptor
at end-of-file. The package revalidates descriptor identity and the observable
metadata fingerprint (mode, size, link count, device, inode, mtime, ctime) and
rejects in-place mutation detected during execution. It does not treat a
mid-archive offset as incomplete consumption.

This distinction matters for a buyer-visible recovery drill: requiring EOF after
a real custom-format restore would fail a usable isolated target after the SQL
transaction had already committed.

## What this slice does not prove

This executor does not prove restored schema/RLS/constraint/extension parity,
target isolation, WAL/PITR, universal RPO/RTO, high availability, disaster
recovery, CSAP, or SOC 2 readiness. Those remain issue #204 and
deployment-specific evidence. Canonical product documentation ownership for the
broader recovery program remains with the documentation authority PR; this note
records only the restore execution and rollback contract.

## Verification

Confirm on the exact current head that:

- implicit or non-boolean source trust fails before `pg_restore` starts;
- ambient host/database/options/SSL-mode variables never reach the child;
- a custom-format seek that leaves the descriptor mid-archive still succeeds
  when metadata is unchanged;
- single-field metadata mutation fails closed;
- initial seek inspection failure is content-free and starts no subprocess;
- production statement and branch coverage and public docstrings remain 100%.

## References

International Organization for Standardization. (2022). *Information security,
cybersecurity and privacy protection — Information security management systems
— Requirements* (ISO/IEC 27001:2022). Control A.8.13 requires information
backup; this package records a bounded logical-restore executor, not a certified
ISMS.

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*.
https://cwe.mitre.org/data/definitions/367.html

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST Special
Publication 800-34 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-34r1

The PostgreSQL Global Development Group. (2026). *Backup and restore*.
PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/backup.html

The PostgreSQL Global Development Group. (2026). *pg_restore*. PostgreSQL 18
documentation. https://www.postgresql.org/docs/current/app-pgrestore.html
