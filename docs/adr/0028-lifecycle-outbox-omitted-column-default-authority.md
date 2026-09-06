# ADR 0028: Lifecycle Outbox Omitted-Column Default Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle durability boundary

## Context

`PostgresContextLifecycleOutboxStore.enqueue_in_transaction()` supplies the tenant and privacy-minimized lifecycle evidence columns but intentionally omits `context_outbox_uuid` and `created_at`. PostgreSQL therefore evaluates the declared defaults for those columns on each newly inserted durable publication intent.

Migration 0008 owns convergence. It establishes the canonical defaults and verifies them while the schema migration is executing. That evidence is not sufficient for final admission after a restore or later operator DDL: the migration can have been recorded as applied and either omitted-column default can subsequently be replaced without changing the table's CHECK constraints, RLS policy, user-trigger/rule inventory, replay key, or index topology. Before this decision, migration 0009 re-proved those other write authorities but did not independently re-read the default expressions.

A changed default is executable write-path authority. In particular, PostgreSQL permits a column default to be an expression and evaluates it when an insert omits that column. A volatile function is therefore capable of rejecting or otherwise altering an otherwise-canonical outbox insert. `pg_attrdef` stores the default expression in `adbin`; PostgreSQL documents `pg_get_expr(adbin, adrelid)` as the supported SQL representation.

The repository currently runs the PostgreSQL 16 container profile. Current PostgreSQL 18 documentation is used as the primary specification because the catalog and default-expression interfaces relied on here are also present in the supported runtime version; acceptance remains executable against the repository's actual PostgreSQL image.

## Decision

Migration 0008 remains the sole convergence owner. Migration 0009 is a fail-closed final verifier and does not repair operator drift.

Before admitting the outbox, migration 0009 must re-read `pg_attribute` and `pg_attrdef` for the two columns the package INSERT omits and prove all of the following:

- `context_outbox_uuid` is a live, non-generated, non-identity, NOT NULL `uuid` column with a default whose deparsed expression is exactly `gen_random_uuid()`;
- `created_at` is a live, non-generated, non-identity, NOT NULL `timestamp with time zone` column with a default whose deparsed expression is exactly `now()`; and
- any mismatch fails through the existing content-free `unexpected lifecycle outbox row-admission authority` boundary.

The package migration and Docker initializer must remain byte-identical. The realistic container acceptance must prove that an operator-supplied `created_at` default function can reject an otherwise-canonical insert and that migration 0009 rejects that catalog state. After explicit test cleanup and restoration of the canonical default, migration 0009 must succeed again.

## Alternatives considered

Trust migration history alone was rejected because a successful earlier migration does not prove current catalog authority after restore or later DDL.

Checking only `pg_attribute.atthasdef` was rejected because it proves only that some default exists, not which expression will execute.

Allow-listing user function names or schemas was rejected because names are mutable metadata and do not establish the package-owned default semantics.

Automatically resetting defaults in migration 0009 was rejected because 0009 is the final admission verifier. Silent repair would erase operator evidence and split convergence authority with migration 0008.

Supplying UUID and timestamp values explicitly from application code was rejected for this repair because it changes the established database-owned durable identity and insertion-time semantics rather than closing the catalog-verification gap.

## Verification and traceability

The TDD/evidence lineage for this decision is:

- static RED `2706d360847a9acfb231f12a46572b9b964a5168`, requiring final `pg_attrdef` verification in migration 0009;
- executable PostgreSQL RED specimen `0f9120de47de99d4233a1e32a228c14208c0ffc5`, demonstrating that an omitted-column default can execute and reject a canonical event;
- CI wiring `ba7f6a5483f1b3e038deef41baa1b72271278c29`;
- package migration repair `d253daf8b7f6487d0a208b4d434f031a43b8ea4a`; and
- Docker mirror repair `2d046e52ae18a9b39ca17605b37d24948116451a`.

This ADR remains Proposed until the unchanged exact head executes the full hosted PostgreSQL/container acceptance and repository quality gates. A queued, pending, stale, predecessor, synthetic, or otherwise non-executed workflow is not GREEN evidence.

## Consequences

A restore or operator that intentionally changes either omitted-column default must reconcile the schema explicitly before the package will admit it. This may turn previously latent drift into an installation failure, which is intentional: the package cannot treat unknown executable default authority as durable lifecycle truth.

The change does not add cross-service SQL, provider coupling, prompt/response storage, a mutable upstream dependency, or new publication authority. It narrows only the pg-llm-batch-owned lifecycle persistence boundary.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Default values*. https://www.postgresql.org/docs/18/ddl-default.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: INSERT*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_attrdef*. https://www.postgresql.org/docs/18/catalog-pg-attrdef.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_attribute*. https://www.postgresql.org/docs/18/catalog-pg-attribute.html
