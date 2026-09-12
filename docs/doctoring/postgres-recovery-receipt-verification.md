# PostgreSQL recovery receipt verification

This record is the operator contract for
`verify_postgres_recovery_receipt()` and ADR 0020. Use it after you have a stored
`PostgresRecoveryReceipt` and the caller-owned backup file that receipt
names. The function re-inspects current bytes. It does not accept
preconstructed evidence objects, and it does not run `pg_dump` or
`pg_restore`.

## What to do next

1. Load the stored receipt with `parse_postgres_recovery_receipt(...)`.
2. Keep the backup file at a caller-owned path you are willing to open
   through `inspect_postgres_backup_artifact()`.
3. Call `verify_postgres_recovery_receipt(receipt,
   backup_artifact_path=...)`. The verifier calls
   `inspect_postgres_schema()` and `inspect_postgres_backup_artifact()`
   itself. Do not pass `PostgresSchemaEvidence` or
   `PostgresBackupArtifactEvidence` objects. Exact-type constructors are
   caller claims, not inspection provenance.
4. Continue to a reviewed isolated restore drill only when verification
   returns. A match is not proof that restore, RLS, PITR, or a live
   cluster succeeded, and it is not a lock against later mutation
   (CWE-367). Re-inspect immediately before `pg_restore` if time has
   passed.
5. If verification raises `PostgresRecoveryVerificationError`, stop. Do
   not edit receipt fields by hand to force a match. Re-inspect the
   packaged schema or the artifact, then retry only with the current
   file.

## Evidence boundary

The verifier compares:

- `schema_sha256` to a fresh `inspect_postgres_schema()` digest;
- `backup_sha256` and `backup_size_bytes` to a fresh
  `inspect_postgres_backup_artifact(backup_artifact_path)` result.

It rejects receipt subclasses and non-string paths before opening the
artifact. It does not accept a parallel digest, size, DSN, credential,
`service_name`, tenant scope, or backup-byte argument. Digest comparison
uses equal-length constant-time matching.

This slice does not execute `pg_dump` or `pg_restore`, does not prove a
backup is restorable, and does not establish RPO/RTO, CSAP, or SOC 2
readiness. It never emits a package capability claim.

## Failure handling

Invalid receipt types or a non-string `backup_artifact_path` raise a
fixed inputs error before filesystem access. A schema digest mismatch
raises a fixed inspected-schema error. A backup digest or size mismatch
raises a fixed inspected-backup error. Inspector failures propagate as
their existing content-free types. Lower-layer values never enter the
verification exception text.

## References

National Institute of Standards and Technology. (2015). *Secure hash
standard (SHS)* (FIPS PUB 180-4).
https://doi.org/10.6028/NIST.FIPS.180-4

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53 Rev. 5).
National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race
condition*. https://cwe.mitre.org/data/definitions/367.html

The PostgreSQL Global Development Group. (2026). *Backup and restore*.
PostgreSQL 18 documentation.
https://www.postgresql.org/docs/18/backup.html

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST
Special Publication 800-34 Rev. 1). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-34r1
