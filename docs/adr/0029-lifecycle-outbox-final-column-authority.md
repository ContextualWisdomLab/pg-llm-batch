# ADR 0029: Lifecycle Outbox Final Column Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch lifecycle durability boundary

## Context

Migration 0008 converges `public.llm_context_lifecycle_outbox` to the package-owned structural schema. Migration 0009 is the later fail-closed row-admission verifier that proves the current relation still has only reviewed write authorities before the package treats it as a durable publication-intent boundary. A successful migration is point-in-time evidence, however: restore or operator DDL can change `pg_attribute` after both migrations have completed while leaving their recorded history unchanged.

Before this decision, migration 0009 re-proved RLS, user triggers and rewrite rules, omitted-column defaults, CHECK semantics, replay/primary-key constraints, and index execution authority, but did not re-prove the complete `pg_attribute` column identity. The migration-side gap was repaired first. Continuing package runtime admission then still trusted that earlier result, so post-migration column drift could be introduced after schema application and accepted by `_require_rls_application_role()`.

That drift is material in more than one catalog dimension. PostgreSQL documents that a CHECK succeeds when its expression is `TRUE` or `UNKNOWN`; common predicates therefore do not reject a null operand. PostgreSQL also treats null values as distinct by default for UNIQUE enforcement. Consequently, dropping `NOT NULL` from `evidence_id` allows multiple otherwise-canonical rows with `evidence_id = NULL` to pass the aggregate payload CHECK and the `(tenant_scope, evidence_id)` replay constraint. Migration history and unchanged named constraints are not sufficient evidence of current replay identity.

`atttypid` is also not complete type identity. PostgreSQL records type-specific table-definition data in `pg_attribute.atttypmod`; values are passed to type-specific input and length-coercion behavior. `timestamp(p) with time zone` uses the same base type OID across precision choices while `p` controls the retained fractional-second digits. The executable #337 specimen changed only canonical unrestricted `created_at timestamptz` (`atttypmod = -1`) to `timestamp(0) with time zone`, retained the same `atttypid`, collation, `NOT NULL`, default-presence, generated/identity state, and `now()` default expression, and demonstrated that stored fractional-second semantics changed. Both migration 0009 and continuing runtime admission nevertheless accepted that state before this repair.

The repository currently executes PostgreSQL 16 in its container acceptance profile. Current PostgreSQL 18 documentation is the primary specification for the catalog, type-modifier, and constraint semantics used here; the decision remains acceptance-tested against the repository's actual supported image.

## Decision

Migration 0008 remains the sole schema-convergence owner. Migration 0009 remains a point-in-time final verifier and must not silently repair post-convergence operator drift. Continuing runtime admission is a separate authority gate: after the package has acquired its retained relation lock and resolved the admitted relation object, `_require_rls_application_role()` must re-read the same canonical column catalog before tenant binding or outbox data I/O. Runtime admission rejects drift; it does not issue convergence DDL.

Tenant-scope value validation and transaction-local tenant binding are distinct boundaries. Store construction validates the authorized tenant scope before any database I/O. On each database path, the retained relation lock and live authority admission intentionally precede `set_config`; only after the application role and relation authority are accepted does the package bind the already-validated scope through parameterized transaction-local `pg_catalog.set_config(...)`, and row access follows that binding. This preserves the established AGENTS read/write ordering rather than exposing tenant-bound row access before authority admission.

Both migration 0009 and continuing runtime admission must prove the canonical column catalog identity:

- exactly 14 live positive-numbered user columns exist and no additional live column is present;
- the exact column names and PostgreSQL base types match the canonical outbox contract;
- every canonical column has the reviewed unrestricted type modifier `atttypmod = -1`; a same-`atttypid` precision or other type-modifier drift is not canonical identity;
- each column's collation matches the default collation recorded by its canonical PostgreSQL type;
- every canonical column retains its reviewed `NOT NULL` state and default-presence state;
- no canonical column has generated-column or identity authority;
- no positive-numbered dropped-column tombstone remains; and
- any mismatch fails through the existing content-free lifecycle-outbox application-authority boundary before tenant binding or data I/O.

The verifier deliberately checks the entire relation rather than only `evidence_id` or `created_at`. A final authority gate that fixes one demonstrated column while continuing to trust the remaining post-migration catalog would preserve the same defect class under another column name. The expected typmod is therefore declared for all 14 canonical columns and compared directly with `actual.atttypmod` in migration and runtime admission.

The package migration and Docker initializer must remain byte-identical. Real PostgreSQL acceptance first removes `NOT NULL` from `evidence_id`, demonstrates that two NULL replay identities are actually admitted by the otherwise-canonical CHECK/UNIQUE topology, proves that migration 0009 rejects that state, and proves that an ordinary `NOSUPERUSER NOBYPASSRLS` SELECT/INSERT application role is rejected by continuing runtime admission before tenant binding or data I/O. It then restores canonical nullability. The same specimen independently changes only `created_at` to `timestamp(0) with time zone`, proves same `atttypid` plus different `atttypmod` and different stored fractional-second behavior while every previously authenticated column/default property stays canonical, and requires both migration 0009 and runtime admission to reject that drift. The specimen restores unrestricted `timestamptz` and requires re-admission to succeed.

## Alternatives considered

Trusting migration 0008 or migration 0009 history was rejected because migration history proves an earlier transition, not current catalog state after restore or later DDL.

Relying on the canonical CHECK and UNIQUE objects was rejected because PostgreSQL explicitly permits CHECK `UNKNOWN` and, by default, multiple null values under UNIQUE constraints.

Checking only `evidence_id.attnotnull` was rejected because the authority boundary owns one canonical relation. Other post-migration column type, type-modifier, nullability, default-presence, generated/identity, additive-column, or dropped-column drift would remain unverified.

Checking only `atttypid` was rejected by executable evidence: unrestricted `timestamptz` and `timestamptz(0)` retained the same type OID while their `atttypmod` and stored fractional-second semantics differed. Treating type OID as complete column type identity would therefore authorize material coercion/storage drift.

Automatically issuing `ALTER COLUMN ... SET NOT NULL` or restoring a canonical typmod from migration 0009 or runtime admission was rejected because existing rows may already reflect altered semantics and because silent repair would erase operator evidence and split convergence authority with migration 0008.

Application-value validation alone was rejected because the durable PostgreSQL table is shared persistence authority. A restore, maintenance client, or future package path must not be able to create a catalog state that PostgreSQL admits while the package's authority gates declare canonical.

Caching a prior successful column verdict across transactions was rejected because it would turn independently mutable PostgreSQL catalog authority into stale application memory without a reviewed invalidation/version contract.

Binding the tenant GUC before live authority admission was rejected for this decision because it reverses the repository's explicit retained-lock -> authority-admission -> tenant-binding -> data-I/O ordering. Tenant context is already validated before database I/O; transaction-local binding is performed only after the runtime credential and canonical relation authority have been accepted and still precedes every lifecycle row access.

## Verification and traceability

The migration-side nullability TDD/evidence lineage is:

- static RED `bd748c15508449d1838cd353382d0684af985dee`, requiring migration 0009 to re-prove the complete final column catalog identity;
- executable PostgreSQL RED specimen `587651ee3403b9d46a63d96311fc93f1687dbd01`, demonstrating that post-0008 `evidence_id` nullability drift admits two NULL replay identities;
- CI wiring `02166deedc44c29ad6b84c1ce366da52823fc09c`;
- package migration repair `2c22348daea015cb919301ac0f8c713aed36cbba`; and
- Docker mirror repair `e7f2079d442af883a490c745cf81f31fcb539332`.

The continuing-runtime nullability lineage is:

- hosted runtime RED `7ba53c79b50f0f1d204f0f282927a71ec95bb301`, with CI `34187484224` failing the PostgreSQL/container lane while package/unit lanes passed; and
- minimum runtime repair `32c100b76764b3da16303f0d080383a4072cf7d0`, which adds the exact 14-column `pg_catalog.pg_attribute`/`pg_type` re-proof to `_require_rls_application_role()` before tenant binding or data I/O.

The same-type typmod lineage is:

- executable PostgreSQL RED `c3916340284950a42b31abc6f39a8d275b003200`, with CI `34193807153` failing only the PostgreSQL/container acceptance path after the specimen proved same `atttypid`, different `atttypmod`, otherwise-canonical admitted properties, and changed fractional-second storage semantics; the terminal diagnostic was `same-atttypid column typmod drift remained admissible: runtime_rejected=0 migration_rejected=0`;
- Release Acceptance `34193807165` succeeded on that RED head, separating artifact reproducibility from the database-authority defect; and
- minimum causal repair `2dd8e10def93b18e8973a99a897b8625763a9e7c`, which adds the reviewed `atttypmod = -1` identity to `_unsafe_outbox_column_sql()`, migration 0009, and its byte-identical Docker initializer without adding convergence DDL.

This ADR remains Proposed until one unchanged exact head executes the hosted PostgreSQL/container specimen and the complete repository quality/release acceptance set successfully, and the change reaches protected integration through normal governance. Queued, pending, stale, predecessor, synthetic, or otherwise non-executed evidence does not promote this decision to Accepted.

## Consequences

A restore or operator that intentionally changes the outbox column catalog must reconcile that relation explicitly before pg-llm-batch admits it. In particular, a relation containing NULL replay identities or values already coerced under a noncanonical type modifier cannot be repaired implicitly by either verifier; the operator must decide how altered durable rows are handled before restoring the canonical catalog.

The column-catalog reads now occur both at schema verification and on continuing package runtime admission. Typmod authentication reuses that existing `pg_attribute` scan but adds another identity comparison; it is still part of the complete buyer path, not removable security overhead. Issue #307 must measure connection acquisition, retained lock acquisition/wait, this `pg_attribute`/`pg_type` probe together with the other authority scans, tenant binding, data I/O, and cleanup under declared catalog/cardinality and concurrency conditions. The commercial p95 target cannot be met by measuring these reads out, shrinking the sample, or relying on an unversioned authority cache.

The repair adds no provider coupling, cross-service SQL, prompt/response retention, mutable upstream dependency, or schema-convergence ownership to runtime code.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Constraints*. https://www.postgresql.org/docs/18/ddl-constraints.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Date/time types*. https://www.postgresql.org/docs/18/datatype-datetime.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: pg_attribute*. https://www.postgresql.org/docs/18/catalog-pg-attribute.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE TABLE*. https://www.postgresql.org/docs/18/sql-createtable.html
