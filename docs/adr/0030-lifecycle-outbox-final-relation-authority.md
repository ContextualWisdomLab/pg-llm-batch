# ADR 0030: Lifecycle Outbox Final Relation Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle durability boundary

## Context

Migration 0008 converges `public.llm_context_lifecycle_outbox` to one ordinary logged table with no PostgreSQL inheritance edge. Migration 0009 is the later fail-closed row-admission verifier used to prove that the current relation still has only reviewed durability and write authorities before pg-llm-batch treats it as durable publication intent.

Before this decision, migration 0009 independently re-proved RLS, table programs, complete column identity, omitted-column defaults, CHECK semantics, constraints, and index programs, but it did not re-prove the relation's `pg_class.relkind` / `relpersistence`, schema identity, or `pg_inherits` topology after 0008 had been recorded as applied.

That gap is material. PostgreSQL documents that UNLOGGED table data is not written to WAL, is not crash-safe, is truncated after a crash or unclean shutdown, and is not replicated to standby servers. PostgreSQL inheritance also changes the relation boundary: parent queries generally include child rows unless `ONLY` is used, while UNIQUE and PRIMARY KEY constraints are not inherited and do not enforce uniqueness across the hierarchy. A later `SET UNLOGGED` or inheritance edge can therefore invalidate the package's durable/replay boundary without changing the already-reviewed columns, RLS policies, CHECKs, UNIQUE constraints, defaults, triggers/rules, or index definitions.

The repository currently executes PostgreSQL 16 in its container acceptance profile. Current PostgreSQL 18 documentation is the primary specification for these durability and inheritance semantics; executable acceptance remains bound to the repository's actual supported image.

## Decision

Migration 0008 remains the sole convergence owner. Migration 0009 remains final verification and must not repair post-convergence relation drift.

Before RLS and later row-admission checks, migration 0009 must prove that the canonical object:

- resolves exactly as `public.llm_context_lifecycle_outbox`;
- is an ordinary relation (`pg_class.relkind = 'r'`);
- is permanently/WAL logged (`pg_class.relpersistence = 'p'`);
- belongs to schema `public`; and
- participates in no `pg_inherits` edge as either child or parent.

Any mismatch raises the existing content-free `unexpected lifecycle outbox row-admission authority` error. Migration 0009 does not execute `SET LOGGED`, detach/attach inheritance, copy/delete data, or rebuild the relation.

Real PostgreSQL acceptance must first change the already-converged outbox to UNLOGGED, prove the catalog state actually changed, require migration 0009 to fail closed, explicitly restore LOGGED, and require re-admission to succeed. It must separately attach a post-convergence inheritance child, prove the edge exists, require migration 0009 to fail closed, then explicitly remove the child and require clean re-admission.

## Alternatives considered

Trusting migration 0008 history was rejected because a successful earlier convergence is not evidence of current relation persistence or topology after restore/operator DDL.

Checking only `relpersistence` was rejected because an inheritance edge can widen ordinary parent-table operations beyond the single aggregate table while leaving persistence logged.

Relying only on runtime `ONLY` reads was rejected because the package owns more than one database operation and migration/recovery/replay authority must remain one canonical physical relation rather than a hierarchy whose constraints have different inheritance semantics.

Automatically executing `ALTER TABLE ... SET LOGGED` was rejected because PostgreSQL storage/WAL work has availability and recovery consequences, and no migration can reconstruct durable intents already lost during an unlogged interval.

Automatically dropping or detaching inheritance children was rejected because the package cannot prove ownership, data-retention obligations, or whether child rows contain independently authoritative records.

## Verification and traceability

The TDD/evidence lineage for this decision is:

- static RED `3b0e6937e13988e091a21599ac5d1c91dc4e5cfb`, requiring migration 0009 to re-prove logged ordinary-public relation identity and absence of inheritance edges;
- executable PostgreSQL RED `29afc8d155fc9efcc5e2fa9778f1809de4434721`, refined by `a00f2c65b1a8576c5403d080d5806a66e32c46f7`, covering both post-0008 UNLOGGED and inheritance drift;
- CI wiring `6407be7dde493bfea343ff16b8bd143da36f0d78`;
- package migration repair `c2a170532fb5fb65cc3994a113f6a53fbeec2c18`; and
- Docker mirror repair `f1a44358662396db091f77f660d1e3647c0625ab`.

This ADR remains Proposed until one unchanged exact head executes the hosted PostgreSQL/container specimens and the complete repository quality/release acceptance set. Queued, pending, stale, predecessor, or otherwise non-executed evidence does not promote this decision to Accepted.

## Consequences

A restore/operator that intentionally changes lifecycle-outbox persistence or inheritance topology must reconcile the database explicitly before pg-llm-batch admits it. If an UNLOGGED interval may have crossed a crash or standby failover, operators must reconcile potentially lost publication intents rather than treating `SET LOGGED` as historical recovery evidence.

The added reads are migration-time catalog checks only and do not affect the batch/lifecycle hot path. They introduce no provider coupling, cross-service SQL, prompt/response retention, or mutable upstream dependency.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Inheritance*. https://www.postgresql.org/docs/18/ddl-inherit.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_class*. https://www.postgresql.org/docs/18/catalog-pg-class.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_inherits*. https://www.postgresql.org/docs/18/catalog-pg-inherits.html
