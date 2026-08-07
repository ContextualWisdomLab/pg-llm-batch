# PostgreSQL checkpoint counter bounds

## Decision

`PostgresBatchResultCheckpointStore` validates every persisted checkpoint counter
before tenant binding or any other SQL statement. `file_line_number`,
`batch_line_count`, and `record_count` must not exceed `9,223,372,036,854,775,807`,
the maximum signed eight-byte integer accepted by PostgreSQL `BIGINT`.

The general in-memory `BatchResultCheckpoint` remains storage-independent. The
PostgreSQL adapter owns this narrower persistence boundary because other host
stores may support wider integers. Both the candidate checkpoint and
`expected_previous` compare-and-swap evidence are checked before database access.
The exact maximum remains valid; the first larger value fails as a structured
`ValidationError` naming the offending nested field. This prevents a driver or
server numeric-overflow exception from aborting a caller-owned transaction after
business work has already begun.

## Verification

Deterministic tests cover overflow through physical-line and record-count paths,
compare-and-swap evidence, the exact legal maximum, and the requirement that no
transaction-local tenant-setting statement or checkpoint query executes for
invalid storage values. Production statement, branch, and public-docstring
coverage remain at 100%.

## Operational consequence

A host approaching the signed `BIGINT` ceiling must rotate to a new logical batch
or adopt a separately versioned schema using an explicitly reviewed wider numeric
representation. Silently coercing, saturating, wrapping, or changing the existing
migration column types is prohibited because it would invalidate checkpoint
identity, ordering, and rollback evidence.

## Reference

PostgreSQL Global Development Group. (n.d.). *8.1. Numeric types*. In
*PostgreSQL 18 documentation*. Retrieved August 7, 2026, from
https://www.postgresql.org/docs/18/datatype-numeric.html
