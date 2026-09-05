# ADR 0019: Pin lifecycle-outbox UUID default authority to PostgreSQL core

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle persistence bounded context

## Problem

`llm_context_lifecycle_outbox.context_outbox_uuid` is a package-owned durable surrogate identity. Migration 0008 previously admitted `uuid_generate_v4()` and `public.uuid_generate_v4()` as equivalent defaults. This repository also provides a public compatibility helper named `uuid_generate_v4()` when an external implementation is absent. That compatibility surface is appropriate for legacy schema consumers, but it is mutable schema-scoped function authority and should not decide future lifecycle-outbox identities after migration convergence.

A restore or manual repair could therefore leave the outbox structurally valid while its next-row identity generation remained delegated to a replaceable `public` function. The row type, primary key, RLS policy, and replay arbiter would all look canonical even though a future UUID default call had different authority.

## Constraints

The repair must preserve existing rows and UUIDs, keep the package and Docker migration bytes identical, remain idempotent after convergence, and not broaden this PR into the separate PostgreSQL-driver lane. It must work on the repository's PostgreSQL 16 baseline. Missing defaults, incompatible UUID types, generated/identity columns, PK drift, and undeclared columns remain structural failures; only an existing noncanonical UUID default expression is eligible for convergence.

## Alternatives

Keeping `public.uuid_generate_v4()` was rejected because its schema object can be replaced independently of the lifecycle aggregate. Adding provenance checks for the helper was rejected because it would turn a compatibility function into a second package-owned trust root without product value. Generating UUIDs in Python was rejected because the database owns this surrogate key and database-side generation preserves atomic insert semantics. Rewriting existing UUIDs was rejected because it would change durable identity and foreign-reference semantics.

## Decision

Fresh outbox creation uses `DEFAULT pg_catalog.gen_random_uuid()`. After structural admission, migration 0008 inspects the installed default with `pg_catalog.pg_get_expr`. If the default does not decompile to the PostgreSQL core `gen_random_uuid()` expression, the migration changes only the column default metadata with `ALTER COLUMN ... SET DEFAULT pg_catalog.gen_random_uuid()`. It then repeats catalog verification and fails closed with a content-free migration error if canonical authority was not established.

The package migration and Docker initializer must remain byte-identical. A static regression requires the fresh default, convergence DDL, and post-verification. A real PostgreSQL container smoke first restores `public.uuid_generate_v4()` as the default, reapplies migration, requires `pg_get_expr` to report `gen_random_uuid()`, and reapplies the migration again to prove converged idempotence.

## Evidence

RED static contract: `4cc77d5740ec9b60d99f49aabf1e9449395f5340`.

RED PostgreSQL specimen: `b48c322486ea17944f566b35bd97201d409735d7`.

CI wiring: `57aed9bf91cf03080e321a3f7a5ff74576cafc62`.

Causal package migration fix: `f6b2bad9ac381ef69510971e6c6d780cfb516dea`.

Byte-identical Docker mirror: `f736deee20391680e9cf32f9901b8fdad4d8d841`; both migration paths use blob `a10df53fc2717de91cceb0c9430e442f47b27620`.

Structural-test alignment: `179354b33d6d0792af9a9ae306e4f094805c4140`.

Exact-head hosted PostgreSQL execution remains required before this repair is called GREEN.

## Consequences

The lifecycle outbox no longer needs the repository's mutable `public.uuid_generate_v4()` compatibility helper for new surrogate identities. Existing rows are untouched. Other legacy tables may continue to use the helper until their own bounded-context migrations deliberately replace it; this ADR does not silently change those schemas.

The convergence DDL may acquire the normal table lock required to change a column default when a stale default is detected. Already-converged installations avoid that DDL. This is a one-time metadata repair, not a table rewrite.

## References

PostgreSQL Global Development Group. (2025). *PostgreSQL 16 documentation: UUID functions*. https://www.postgresql.org/docs/16/functions-uuid.html

PostgreSQL Global Development Group. (2025). *PostgreSQL 16 documentation: F.28. pgcrypto*. https://www.postgresql.org/docs/16/pgcrypto.html

PostgreSQL Global Development Group. (2025). *PostgreSQL 16 documentation: F.49. uuid-ossp*. https://www.postgresql.org/docs/16/uuid-ossp.html

PostgreSQL Global Development Group. (2025). *PostgreSQL 16 documentation: 53.6. pg_attrdef*. https://www.postgresql.org/docs/16/catalog-pg-attrdef.html
