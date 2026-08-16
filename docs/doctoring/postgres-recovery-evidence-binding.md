# PostgreSQL recovery evidence binding

This doctoring note tells an operator how to compose already-inspected schema
and backup-artifact evidence into one content-free recovery receipt. Use it when
you have a private backup file and need machine evidence that names the exact
package schema and artifact identity before you restore or hand the artifact to
another host.

## Next action

1. Inspect the packaged schema with `inspect_postgres_schema()`.
2. Inspect the caller-owned backup file with
   `inspect_postgres_backup_artifact(path)`.
3. Call `bind_postgres_recovery_receipt(...)` with those exact evidence objects
   plus package version, source commit, PostgreSQL major version, reviewed
   backup method, and bounded start/end epochs.
4. Persist or compare the returned `PostgresRecoveryReceipt` JSON. Do not treat
   the receipt as proof that restore, RLS, PITR, or a live cluster succeeded.

If binding raises `PostgresRecoveryBindingError`, stop. Re-inspect the schema
and artifact, then retry only with the new evidence objects. Do not edit receipt
fields by hand to force a match.

## Evidence boundary

The binder copies:

- `schema_sha256` from `PostgresSchemaEvidence`;
- `backup_sha256` and `backup_size_bytes` from `PostgresBackupArtifactEvidence`.

It rejects subclasses and attribute-shaped substitutes before reading digests.
It does not accept a parallel digest or size argument, so a caller cannot attach
a hash from one file to the size of another. Paths, DSNs, credentials,
`service_name`, tenant scope, and backup bytes never enter the receipt.

`backup_method` is a reviewed profile label (`logical`, `physical`, or `pitr`).
It is not tenant authorization and does not select a restore target.

This slice does not execute `pg_dump` or `pg_restore`, does not prove a backup
is restorable, and does not establish RPO/RTO, CSAP, or SOC 2 readiness.

## Failure handling

Invalid evidence types or internally malformed evidence raise a fixed inputs
error. Identity metadata that the receipt schema rejects raises a fixed
metadata error. Lower-layer receipt diagnostics are discarded. Retry only after
correcting the caller-supplied identity or re-inspecting the files.

## References

National Institute of Standards and Technology. (2015). *Secure hash standard
(SHS)* (FIPS PUB 180-4). https://doi.org/10.6028/NIST.FIPS.180-4

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation:
Chapter 25. Backup and restore*. https://www.postgresql.org/docs/18/backup.html

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST Special
Publication 800-34 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-34r1

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53 Rev. 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5
