# ADR 0028: Lifecycle Outbox Final Table-Program Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle / PostgreSQL persistence boundary

## Context

`pg-llm-batch` owns the durable lifecycle outbox and its tenant-isolation boundary. Migration 0008 converges the table and already rejects user-defined table triggers and rewrite rules while validating structural schema. Migration 0009 is a separate final row-admission verifier: it re-proves RLS, canonical CHECK semantics, constraints, indexes, and operator-class authority after convergence.

That split left one recovery/manual-DDL gap. After migration 0008 had been recorded as applied, an operator or restore could attach a user trigger or rewrite rule. Migration 0009 did not re-read `pg_trigger` or `pg_rewrite`, so it could admit a table whose visible columns, constraints, indexes, and RLS were canonical while write behavior was no longer canonical.

This is executable authority rather than metadata-only drift. PostgreSQL documents that `pg_trigger` stores triggers on tables and views, `tgrelid` identifies the target relation, `tgfoid` identifies the function called, and `tgisinternal` distinguishes internally generated triggers. PostgreSQL also documents that `pg_rewrite` stores rewrite rules for tables and views and that `ev_class` identifies the relation whose query tree is rewritten.

## Decision

Migration 0009 MUST fail closed when the canonical lifecycle outbox has either:

- any `pg_trigger` row for the outbox where `tgisinternal = false`; or
- any `pg_rewrite` row whose `ev_class` is the outbox relation.

Internal PostgreSQL constraint triggers remain admissible. The package does not delete, disable, rename, or reinterpret unknown user triggers or rewrite rules. Their ownership, side effects, and retention requirements cannot be inferred safely by the lifecycle migration, so remediation is operator-controlled reconciliation followed by a fresh migration-0009 admission check.

Migration 0008 remains the convergence owner. Migration 0009 remains a verifier and does not repair post-convergence operator drift. Package and Docker copies of migration 0009 remain byte-identical.

## Alternatives considered

### Rely only on migration 0008

Rejected. Migration history is not current catalog evidence. A restore or manual DDL operation can attach executable relation programs after 0008 was previously applied.

### Permit triggers or rules by name allow-list

Rejected. Names do not establish behavior, function identity, firing mode, rule action, or side-effect boundaries. An allow-list would turn naming convention into execution authority.

### Automatically drop unknown triggers or rules

Rejected. The migration cannot prove ownership, legal retention requirements, observability dependencies, or operator intent. Destructive cleanup would exceed the bounded context.

### Detect only at runtime enqueue

Rejected. Runtime-only detection leaves deployment/schema admission unable to prove the durable boundary before traffic. The catalog is the authoritative place to reject the unsupported topology.

## Verification

TDD lineage on the #319 branch:

- static RED `121c3f9e100a5ec11e4ddd885753e23b8d97376c` requires migration 0009 to inspect both `pg_trigger` and `pg_rewrite`;
- executable PostgreSQL RED `e6ab6525ca6eaf5d6b175280c4e3a94fa7d865bf` demonstrates a `BEFORE INSERT` trigger rejecting an otherwise canonical event and an `INSTEAD NOTHING` rewrite rule suppressing an otherwise canonical insert, then requires migration 0009 to reject each topology;
- causal fix `31e819938a1fbb4a704d2756f1727caf93198571` adds the final catalog verifier to both package and Docker migrations without broadening convergence authority.

This ADR remains Proposed until hosted CI executes the exact-head PostgreSQL/container acceptance containing those specimens. A queued or predecessor run is not acceptance evidence.

## Consequences

The final admission gate is stricter after restore/manual DDL and can intentionally block startup or migration when operator-owned table programs exist. That is preferable to silently accepting a durable outbox whose write semantics differ from the package contract.

The decision does not claim protection from PostgreSQL superuser/catalog tampering. Production application roles remain `NOSUPERUSER NOBYPASSRLS`, and administrative identities remain outside the ordinary tenant-isolation guarantee.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.58. pg_trigger*. https://www.postgresql.org/docs/18/catalog-pg-trigger.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.45. pg_rewrite*. https://www.postgresql.org/docs/18/catalog-pg-rewrite.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 37.1. Overview of trigger behavior*. https://www.postgresql.org/docs/18/trigger-definition.html
