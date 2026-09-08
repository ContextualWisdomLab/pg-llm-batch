# ADR 0029: Lifecycle Outbox Final Column Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle durability boundary

## Context

Migration 0008 converges `public.llm_context_lifecycle_outbox` to the package-owned structural schema. Migration 0009 is the later fail-closed row-admission verifier that proves the current relation still has only reviewed write authorities before the package treats it as a durable publication-intent boundary. A successful migration is point-in-time evidence, however: restore or operator DDL can change `pg_attribute` after both migrations have completed while leaving their recorded history unchanged.

Before this decision, migration 0009 re-proved RLS, user triggers and rewrite rules, omitted-column defaults, CHECK semantics, replay/primary-key constraints, and index execution authority, but did not re-prove the complete `pg_attribute` column identity. The migration-side gap was repaired first. Continuing package runtime admission then still trusted that earlier result, so post-migration column drift could be introduced after schema application and accepted by `_require_rls_application_role()`.

That drift is material. PostgreSQL documents that a CHECK succeeds when its expression is `TRUE` or `UNKNOWN`; common predicates therefore do not reject a null operand. PostgreSQL also treats null values as distinct by default for UNIQUE enforcement. Consequently, dropping `NOT NULL` from `evidence_id` allows multiple otherwise-canonical rows with `evidence_id = NULL` to pass the aggregate payload CHECK and the `(tenant_scope, evidence_id)` replay constraint. Migration history and unchanged named constraints are not sufficient evidence of current replay identity.

The repository currently executes PostgreSQL 16 in its container acceptance profile. Current PostgreSQL 18 documentation is the primary specification for the catalog and constraint semantics used here; the decision remains acceptance-tested against the repository's actual supported image.

## Decision

Migration 0008 remains the sole schema-convergence owner. Migration 0009 remains a point-in-time final verifier and must not silently repair post-convergence operator drift. Continuing runtime admission is a separate authority gate: after the package has acquired its retained relation lock and resolved the admitted relation object, `_require_rls_application_role()` must re-read the same canonical column catalog before tenant binding or outbox data I/O. Runtime admission rejects drift; it does not issue convergence DDL.

Both migration 0009 and continuing runtime admission must prove the canonical column catalog identity:

- exactly 14 live positive-numbered user columns exist and no additional live column is present;
- the exact column names and PostgreSQL types match the canonical outbox contract;
- each column's collation matches the default collation recorded by its canonical PostgreSQL type;
- every canonical column retains its reviewed `NOT NULL` state and default-presence state;
- no canonical column has generated-column or identity authority;
- no positive-numbered dropped-column tombstone remains; and
- any mismatch fails through the existing content-free lifecycle-outbox application-authority boundary before tenant binding or data I/O.

The verifier deliberately checks the entire relation rather than only `evidence_id`. A final authority gate that fixes one demonstrated column while continuing to trust the remaining post-migration catalog would preserve the same defect class under another column name.

The package migration and Docker initializer must remain byte-identical. Real PostgreSQL acceptance removes `NOT NULL` from `evidence_id`, demonstrates that two NULL replay identities are actually admitted by the otherwise-canonical CHECK/UNIQUE topology, proves that migration 0009 rejects that state, and now also proves that an ordinary `NOSUPERUSER NOBYPASSRLS` SELECT/INSERT application role is rejected by continuing runtime admission before tenant binding or data I/O. The specimen then explicitly deletes the invalid rows, restores `NOT NULL`, and requires re-admission to succeed.

## Alternatives considered

Trusting migration 0008 or migration 0009 history was rejected because migration history proves an earlier transition, not current catalog state after restore or later DDL.

Relying on the canonical CHECK and UNIQUE objects was rejected because PostgreSQL explicitly permits CHECK `UNKNOWN` and, by default, multiple null values under UNIQUE constraints.

Checking only `evidence_id.attnotnull` was rejected because the authority boundary owns one canonical relation. Other post-migration column type, nullability, default-presence, generated/identity, additive-column, or dropped-column drift would remain unverified.

Automatically issuing `ALTER COLUMN ... SET NOT NULL` from migration 0009 or runtime admission was rejected because existing rows may already violate the contract and because silent repair would erase operator evidence and split convergence authority with migration 0008.

Application-value validation alone was rejected because the durable PostgreSQL table is shared persistence authority. A restore, maintenance client, or future package path must not be able to create a catalog state that PostgreSQL admits while the package's authority gates declare canonical.

Caching a prior successful column verdict across transactions was rejected because it would turn independently mutable PostgreSQL catalog authority into stale application memory without a reviewed invalidation/version contract.

## Verification and traceability

The migration-side TDD/evidence lineage is:

- static RED `bd748c15508449d1838cd353382d0684af985dee`, requiring migration 0009 to re-prove the complete final column catalog identity;
- executable PostgreSQL RED specimen `587651ee3403b9d46a63d96311fc93f1687dbd01`, demonstrating that post-0008 `evidence_id` nullability drift admits two NULL replay identities;
- CI wiring `02166deedc44c29ad6b84c1ce366da52823fc09c`;
- package migration repair `2c22348daea015cb919301ac0f8c713aed36cbba`; and
- Docker mirror repair `e7f2079d442af883a490c745cf81f31fcb539332`.

The continuing-runtime lineage is:

- hosted runtime RED `7ba53c79b50f0f1d204f0f282927a71ec95bb301`, with CI `34187484224` failing the PostgreSQL/container lane while package/unit lanes passed; and
- minimum runtime repair `32c100b76764b3da16303f0d080383a4072cf7d0`, which adds the exact 14-column `pg_catalog.pg_attribute`/`pg_type` re-proof to `_require_rls_application_role()` before tenant binding or data I/O.

This ADR remains Proposed until one unchanged exact head executes the hosted PostgreSQL/container specimen and the complete repository quality/release acceptance set successfully, and the change reaches protected integration through normal governance. Queued, pending, stale, predecessor, synthetic, or otherwise non-executed evidence does not promote this decision to Accepted.

## Consequences

A restore or operator that intentionally changes the outbox column catalog must reconcile that relation explicitly before pg-llm-batch admits it. In particular, a relation containing NULL replay identities cannot be repaired implicitly by either verifier; the operator must decide how invalid durable rows are handled before restoring the canonical constraint.

The column-catalog reads now occur both at schema verification and on continuing package runtime admission. They are therefore part of the complete buyer path, not removable security overhead. Issue #307 must measure connection acquisition, retained lock acquisition/wait, this `pg_attribute`/`pg_type` probe together with the other authority scans, tenant binding, data I/O, and cleanup under declared catalog/cardinality and concurrency conditions. The commercial p95 target cannot be met by measuring these reads out, shrinking the sample, or relying on an unversioned authority cache.

The repair adds no provider coupling, cross-service SQL, prompt/response retention, mutable upstream dependency, or schema-convergence ownership to runtime code.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Constraints*. https://www.postgresql.org/docs/18/ddl-constraints.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_attribute*. https://www.postgresql.org/docs/18/catalog-pg-attribute.html
