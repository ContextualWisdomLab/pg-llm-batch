# ADR 0016: Accept custom-format pg_restore seek positions

- **Status:** Accepted for the bounded logical-restore executor
- **Date:** 2026-08-16

## Context

`restore_postgres_logical_backup()` runs one shell-free, single-transaction
`pg_restore` against a caller-owned private regular archive descriptor. An
earlier slice treated a final descriptor offset other than the archive size as
incomplete consumption.

PostgreSQL custom-format archives allow `pg_restore` to reorder archived items.
The official `pg_restore` documentation requires a regular file, not a pipe,
when random access is needed. The child therefore seeks to the table of
contents and data blocks. The final file position is the last seek-and-read
location, which is not guaranteed to be end-of-file even after a complete
restore.

Requiring EOF after a successful custom-format restore would reject a usable
isolated target after `--single-transaction` had already committed. That is a
buyer-visible recovery gap: the SQL change is done, but the Python API reports
failure.

## Decision

Post-restore verification keeps the observable metadata fingerprint and a
fail-closed descriptor inspection. It does not require the descriptor offset to
equal the archive size. Callers must treat a post-restore metadata mismatch as
unsafe because the SQL transaction may already have committed.

The caller-owned `source_superusers_trusted` precondition, the
`--dbname=service=...` selector, the inherited libpq allowlist
(`PGPASSWORD`, `PGPASSFILE`, `PGSERVICEFILE`), and
`--single-transaction --exit-on-error` remain unchanged. The service name is
not an authorization boundary.

## Consequences

A realistic custom-format restore that seeks through the archive can succeed.
A stub `pg_restore` that exits zero without reading is no longer rejected by
offset. That residual is accepted because the executable path is a
caller-supplied authority and offset is not a reliable consumption signal for
seekable custom archives.

Issue #204 remains the integration authority for isolated schema, RLS,
constraint, extension, and PITR acceptance. This decision does not claim CSAP
or SOC 2 readiness.

## Rollback

Restore the EOF consumption check only if a later reviewed contract proves that
every supported archive format leaves the shared descriptor at end-of-file.
Reverting without that proof would again fail live custom-format restores after
commit. Rollback is code and documentation only; no schema migration is
required.

## References

Swanson, M., Bowen, P., Phillips, A., Gallup, D., & Lynes, D. (2010).
*Contingency planning guide for federal information systems* (NIST Special
Publication 800-34 Rev. 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-34r1

The PostgreSQL Global Development Group. (2026). *pg_restore*. PostgreSQL 18
documentation. https://www.postgresql.org/docs/current/app-pgrestore.html
