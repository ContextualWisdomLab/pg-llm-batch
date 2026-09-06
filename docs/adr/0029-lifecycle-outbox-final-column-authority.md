# ADR 0029: Lifecycle Outbox Final Column Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle durability boundary

## Context

Migration 0008 converges `public.llm_context_lifecycle_outbox` to the package-owned structural schema and rejects unexpected live or dropped columns at that point. Migration 0009 is the later fail-closed row-admission verifier used to prove that the current relation still has only reviewed write authorities before the package treats it as a durable publication-intent boundary.

Before this decision, migration 0009 re-proved RLS, user triggers and rewrite rules, omitted-column defaults, CHECK semantics, replay/primary-key constraints, and index execution authority, but did not re-prove the complete `pg_attribute` column identity. A restore or later operator DDL could therefore remove `NOT NULL` from a payload or replay-key column after migration 0008 had been recorded as applied while leaving all of those other catalog objects unchanged.

That drift is material. PostgreSQL documents that a CHECK succeeds when its expression is `TRUE` or `UNKNOWN`; common predicates therefore do not reject a null operand. PostgreSQL also treats null values as distinct by default for UNIQUE enforcement. Consequently, dropping `NOT NULL` from `evidence_id` allows multiple otherwise-canonical rows with `evidence_id = NULL` to pass the aggregate payload CHECK and the `(tenant_scope, evidence_id)` replay constraint. Migration history and unchanged named constraints are not sufficient evidence of current replay identity.

The repository currently executes PostgreSQL 16 in its container acceptance profile. Current PostgreSQL 18 documentation is the primary specification for the catalog and constraint semantics used here; the decision remains acceptance-tested against the repository's actual supported image.

## Decision

Migration 0008 remains the sole schema-convergence owner. Migration 0009 remains a final verifier and must not silently repair post-convergence operator drift.

Before checking executable defaults, CHECK predicates, constraints, or indexes, migration 0009 must re-read `pg_catalog.pg_attribute` and prove the complete canonical column catalog identity:

- exactly 14 live positive-numbered user columns exist and no additional live column is present;
- the exact column names and PostgreSQL types match the canonical outbox contract;
- each column's collation matches the default collation recorded by its canonical PostgreSQL type;
- every canonical column retains its reviewed `NOT NULL` state and default-presence state;
- no canonical column has generated-column or identity authority;
- no positive-numbered dropped-column tombstone remains; and
- any mismatch fails through the existing content-free `unexpected lifecycle outbox row-admission authority` boundary.

The verifier deliberately checks the entire relation rather than only `evidence_id`. A final authority gate that fixes one demonstrated column while continuing to trust the remaining post-0008 catalog would preserve the same defect class under another column name.

The package migration and Docker initializer must remain byte-identical. Real PostgreSQL acceptance must remove `NOT NULL` from `evidence_id`, demonstrate that two NULL replay identities are actually admitted by the otherwise-canonical CHECK/UNIQUE topology, prove that migration 0009 rejects that state, then explicitly delete the invalid specimen, restore `NOT NULL`, and require re-admission to succeed.

## Alternatives considered

Trusting migration 0008 history was rejected because migration history proves an earlier transition, not current catalog state after restore or later DDL.

Relying on the canonical CHECK and UNIQUE objects was rejected because PostgreSQL explicitly permits CHECK `UNKNOWN` and, by default, multiple null values under UNIQUE constraints.

Checking only `evidence_id.attnotnull` was rejected because the final verifier owns one canonical relation boundary. Other post-0008 column type, nullability, default-presence, generated/identity, additive-column, or dropped-column drift would remain unverified.

Automatically issuing `ALTER COLUMN ... SET NOT NULL` in migration 0009 was rejected because existing rows may already violate the contract and because silent repair would erase operator evidence and split convergence authority with migration 0008.

Application-only validation was rejected because the durable PostgreSQL table is shared persistence authority. A restore, maintenance client, or future package path must not be able to create a catalog state that the database itself admits while the final schema verifier declares canonical.

## Verification and traceability

The TDD/evidence lineage for this decision is:

- static RED `bd748c15508449d1838cd353382d0684af985dee`, requiring migration 0009 to re-prove the complete final column catalog identity;
- executable PostgreSQL RED specimen `587651ee3403b9d46a63d96311fc93f1687dbd01`, demonstrating that post-0008 `evidence_id` nullability drift admits two NULL replay identities;
- CI wiring `02166deedc44c29ad6b84c1ce366da52823fc09c`;
- package migration repair `2c22348daea015cb919301ac0f8c713aed36cbba`; and
- Docker mirror repair `e7f2079d442af883a490c745cf81f31fcb539332`.

This ADR remains Proposed until one unchanged exact head executes the hosted PostgreSQL/container specimen and the complete repository quality/release acceptance set. Queued, pending, stale, predecessor, synthetic, or otherwise non-executed evidence does not promote this decision to Accepted.

## Consequences

A restore or operator that intentionally changes the outbox column catalog must reconcile that relation explicitly before pg-llm-batch admits it. In particular, a relation containing NULL replay identities cannot be repaired implicitly by the final verifier; the operator must decide how invalid durable rows are handled before restoring the canonical constraint.

The additional catalog reads occur only during schema admission, not on the batch or lifecycle hot path. They add no provider coupling, cross-service SQL, prompt/response retention, or mutable upstream dependency.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Constraints*. https://www.postgresql.org/docs/18/ddl-constraints.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_attribute*. https://www.postgresql.org/docs/18/catalog-pg-attribute.html
