# PostgreSQL recovery receipt verification

This doctoring note tells an operator how to prove a stored content-free
recovery receipt still names the packaged schema and caller-owned backup
artifact that are about to be restored. Use it after inspect, and after bind
when that seam is available, before you hand the artifact to `pg_restore` or
another host.

## Next action

1. Load the stored `PostgresRecoveryReceipt` with
   `parse_postgres_recovery_receipt(...)`.
2. Re-inspect the packaged schema with `inspect_postgres_schema()`.
3. Re-inspect the caller-owned backup file with
   `inspect_postgres_backup_artifact(path)`.
4. Call `verify_postgres_recovery_receipt(receipt, schema_evidence=...,
   backup_evidence=...)`.
5. Continue to a reviewed isolated restore drill only when verification
   returns. Do not treat a match as proof that restore, RLS, PITR, or a live
   cluster succeeded.

If verification raises `PostgresRecoveryVerificationError`, stop. Re-inspect
the schema or artifact named by the fixed error, then retry only with the new
evidence objects. Do not edit receipt fields by hand to force a match.

## Evidence boundary

The verifier compares:

- `schema_sha256` to `PostgresSchemaEvidence.sha256`;
- `backup_sha256` and `backup_size_bytes` to
  `PostgresBackupArtifactEvidence`.

It rejects subclasses and attribute-shaped substitutes before comparing
digests. It does not accept a parallel digest, size, path, DSN, credential,
`service_name`, tenant scope, or backup-byte argument. Digest comparison uses
equal-length constant-time matching so a mismatch does not become a timing
oracle.

This slice does not execute `pg_dump` or `pg_restore`, does not prove a backup
is restorable, and does not establish RPO/RTO, CSAP, or SOC 2 readiness.

## Failure handling

Invalid receipt or evidence types, or internally malformed evidence, raise a
fixed inputs error. A schema digest mismatch raises a fixed schema-match
error. A backup digest or size mismatch raises a fixed backup-match error.
Lower-layer values never enter the exception text. Retry only after
re-inspecting the disagreeing object.

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

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*.
https://cwe.mitre.org/data/definitions/367.html
