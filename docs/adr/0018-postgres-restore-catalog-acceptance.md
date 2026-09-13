# ADR 0018: Isolated restore catalog acceptance without executor authority

- **Status:** Proposed
- **Date:** 2026-08-16

## Context

Protected main can hash a backup artifact and the packaged `schema.sql` resource,
and it can encode a content-free recovery receipt. Those primitives do not prove
that an isolated restore target contains the package-owned tables, tenant-status
indexes, or forced row-level security that a buyer needs before using the
database again.

Executable `pg_dump` and `pg_restore` remain separate active writers. A catalog
acceptance probe must not open a package-owned connection, must not execute
backup or restore, and must not treat a receipt or hash as restorability.

PostgreSQL publishes `relrowsecurity` and `relforcerowsecurity` on `pg_class`
as the catalog truth for whether row-level security is enabled and whether it
also applies to the table owner (PostgreSQL Global Development Group, 2026b,
2026c). Index ownership, key identity, uniqueness, validity, and access method
are published on `pg_index` and `pg_am`, and `pg_get_indexdef` reconstructs
each key when a column number is supplied (PostgreSQL Global Development
Group, 2026d, 2026e, 2026f). Contingency planning requires proving that
recovered information-system state is usable, not only that a backup command
returned zero (Swanson et al., 2010).

## Decision

Add `inspect_postgres_restore_catalog(connection)` as a caller-owned catalog
probe:

1. The caller supplies an already-authorized connection. The package does not
   parse a DSN, inherit libpq defaults, or create a connection.
2. The probe reads `pg_class` in `current_schema()` through one parameterized
   query. Relation names and kinds are bound; they are never concatenated into
   SQL.
3. Required packaged-schema tables and the tenant-qualified lifecycle unique
   index plus tenant-status index must be present. Those indexes must belong to
   `llm_remote_batch_jobs`, use the packaged key order, stay valid and ready,
   remain plain btree indexes with default key options, and, for the unique
   identity, remain a non-deferrable unique constraint. Missing or same-name
   decoy objects fail closed.
4. `llm_remote_batch_jobs` must have row-level security enabled and forced.
   If `llm_result_stream_checkpoints` is present, it must also be forced. A
   schema-init target that has not applied migration 0007 may omit the
   checkpoint store.
5. Evidence is content-free: counts, boolean RLS flags, and the packaged schema
   SHA-256/size from `inspect_postgres_schema()`. Paths, DSNs, SQL text, and
   lower-layer diagnostics never enter the evidence or exception text.
6. Success does not mean a backup is restorable, a live cluster matches every
   constraint/function body, PITR works, or a stated RPO/RTO is met.

## Consequences

Operators can fail an isolated restore target before they point production
traffic at it, using the same packaged schema identity already hashed on
protected main. Backup and restore executors stay on their own lanes. Canonical
PRD/TRD/CHANGELOG status remains owned by those writers until this probe
integrates.

## Rollback

Remove `pg_llm_batch/postgres_restore_acceptance.py`, its tests, this ADR, and
the doctoring record. No schema migration or durable state conversion is
required.

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
