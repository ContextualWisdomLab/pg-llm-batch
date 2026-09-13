# Isolated PostgreSQL restore catalog acceptance

## What to do next

After you restore into an isolated libpq target, call
`inspect_postgres_restore_catalog(connection)` on a connection you already
opened to that target. Do not point production traffic at the target until the
probe returns. If it raises, keep the target isolated, do not retry a
transactional restore into the same service, and compare the packaged schema
hash on the evidence with the backup you intended to apply.

## Claim boundary

This probe proves that the caller-owned connection can see the required
package-owned tables, the tenant-qualified lifecycle unique index, the
tenant-status index, and forced row-level security on
`llm_remote_batch_jobs`. The required indexes must belong to
`llm_remote_batch_jobs` and match the packaged key order, uniqueness,
validity, readiness, btree access method, and default key options. A
same-name index on another table, with swapped keys, or without the unique
constraint, is incomplete. If `llm_result_stream_checkpoints` is present, it
must also be forced.

It does **not** execute `pg_dump` or `pg_restore`, open a package-owned
connection, prove every constraint or function body, prove live-cluster parity
with `schema.sql` byte-for-byte, authenticate an operator, or establish
PITR/RPO/RTO/HA/DR, CSAP, or SOC 2 readiness. A recovery receipt or artifact
hash is not acceptance.

## Operator contract

1. Restore only into an isolated target whose credentials you already trust.
2. Open the connection yourself. Pass that connection object. The package never
   reads a DSN for this probe.
3. On success, record the returned `expected_schema_sha256` and
   `expected_schema_size_bytes` next to the backup artifact hash you already
   have. Those values come from the packaged `schema.sql` resource, not from
   hashing the live cluster.
4. Treat `checkpoint_store_present=false` as a schema-init target that has not
   applied migration 0007. Do not treat it as proof that checkpoints were
   intentionally empty.
5. On `PostgresRestoreAcceptanceError`, read only the fixed category. The
   exception text never contains SQL, DSNs, passwords, or catalog dumps.

## Verification

Focused tests prove a complete isolated catalog is accepted, a missing
lifecycle table or tenant-status index is incomplete, unforced lifecycle or
checkpoint RLS fails tenant-isolation checks, hostile name subclasses and
lower-layer diagnostics stay out of exceptions, and the probe binds
`current_schema()` with parameters. The catalog SQL is bound to the packaged
`UNIQUE (tenant_scope, endpoint_alias, remote_batch_id)` and
`idx_llm_remote_batch_jobs_tenant_status_observed` column order. The
container smoke creates same-name decoys on the live packaged image and
requires `inspect_postgres_restore_catalog` to fail closed, then restore the
packaged indexes and accept again. Coverage for
`pg_llm_batch.postgres_restore_acceptance` is 100% statement and branch.
Public docstrings are complete.

## References

PostgreSQL Global Development Group. (2026a). *Backup and restore*. In
*PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/backup.html

PostgreSQL Global Development Group. (2026b). *pg_class*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-class.html

PostgreSQL Global Development Group. (2026c). *Row security policies*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026d). *pg_index*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-index.html

PostgreSQL Global Development Group. (2026e). *pg_am*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-am.html

PostgreSQL Global Development Group. (2026f). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST Special
Publication 800-34 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-34r1
