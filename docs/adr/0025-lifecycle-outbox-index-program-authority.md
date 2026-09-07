# ADR 0025: Lifecycle Outbox Index-Program Authority

- Status: Proposed
- Date: 2026-09-06
- Updated: 2026-09-07
- Owners: pg-llm-batch

## Context

`public.llm_context_lifecycle_outbox` is the pg-llm-batch durability boundary for tenant-scoped lifecycle publication intent. Migration 0009 already rejects unknown CHECK/FK/PK/UNIQUE/EXCLUDE constraints, standalone UNIQUE indexes, expression and partial indexes, and custom operator-class authority.

PostgreSQL computes index expressions for row insertion and non-HOT updates, and a partial-index predicate decides whether a row receives an index entry. PostgreSQL also records the operator class chosen for every index key in `pg_index.indclass`. An operator class defines index semantics for a data type/access-method pair and supplies support functions; PostgreSQL explicitly states that index machinery invokes operator-class functions without checking execute privileges. A user-defined operator class can therefore retain executable index authority while maintaining an otherwise plain, non-unique column index even after the application identity itself cannot execute the support function directly.

Migration-time verification alone is temporal evidence. A privileged operator can attach an expression index, partial index, noncanonical unique index, or custom-opclass index after migrations 0008/0009 succeeded and later revoke the privilege that created it. The persistent index remains row-admission authority for subsequent outbox DML. Fresh review found that `_require_rls_application_role()` re-proved live RLS, role, definer, view/materialized/inheritance/foreign-data, trigger, and rewrite-rule authority before tenant binding, but did not re-read the outbox's live `pg_index`/`pg_opclass` state.

The active container target remains PostgreSQL 16, while PostgreSQL 18 documentation is used as the latest primary catalog/interface reference. The relevant `pg_index`, `pg_opclass`, expression/partial-index, and operator-class semantics are compatible with the target contract exercised by the container smoke.

## Decision

Migration 0009 and runtime admission both fail closed when an index attached to the lifecycle outbox has `pg_index.indexprs IS NOT NULL` or `pg_index.indpred IS NOT NULL`.

For every simple index key, both boundaries require the selected operator class to:

- belong to `pg_catalog`;
- be the default operator class for the exact indexed column type;
- belong to the same access method as the index relation; and
- match the table attribute type recorded for that key position.

Both boundaries also reject standalone UNIQUE indexes unless `pg_constraint.conindid` proves that the index backs either the exact canonical primary key on `context_outbox_uuid` or the exact nondeferrable `(tenant_scope, evidence_id)` replay constraint. This rejects post-migration uniqueness drift that can change write acceptance without altering the package DML.

Runtime `_require_rls_application_role()` performs the live index predicate in the same authority query that already checks RLS, attached trigger/rule programs, role delegation, callable definers, views, materialized copies, inheritance/partition topology, and foreign-data reachability. The check runs before tenant `set_config` and before outbox data SQL. A prior migration receipt, later revocation of installer privileges, or the runtime role's inability to create another index is not continuing authorization for the existing index object.

This keeps PostgreSQL-core simple-column operational indexes available while rejecting operator-selected executable programs and noncanonical uniqueness arbiters. In particular, a non-unique built-in hash index using PostgreSQL's default `pg_catalog` operator class remains admissible.

The application isolation contract already excludes arbitrary superuser/catalog mutation from tenant authority. The default `pg_catalog` operator-class identity is therefore treated as PostgreSQL-core authority rather than attempting to defend against a database superuser replacing core catalog objects.

Unknown expression, partial, unique-arbiter, or custom-opclass indexes are not auto-dropped. Their function dependencies, performance role, retention consequences, and ownership require explicit operator reconciliation.

Package migration 0009 and its Docker initializer remain byte-identical. Runtime re-verification does not move convergence ownership out of the migrations.

## Alternatives rejected

Migration-only verification was rejected because migration history is not current catalog evidence after restore, manual DDL, or later privileged administration. The same temporal failure mode already applies to post-migration trigger and rewrite-rule drift.

Allowing non-unique expression indexes was rejected because uniqueness is not the only way an index can alter write acceptance: index expressions are computed during insertion and non-HOT updates and can fail.

Allowing partial indexes solely because their predicate is not a uniqueness arbiter was rejected because the predicate is executable catalog state selected outside the package-owned lifecycle contract.

Treating every plain non-unique column index as inert was rejected because the selected operator class supplies support functions that index machinery can execute without function-permission checks.

Restricting all allowed indexes to btree was rejected as broader than the causal boundary. A PostgreSQL-core non-unique hash index with the default `pg_catalog` operator class does not introduce operator-selected support-function authority and remains an ordinary operational index choice.

Allow-listing function names was rejected because name identity does not prove function body, dependency, language, ownership, or operator-class identity and would introduce another mutable authority surface.

Automatically dropping unknown indexes or operator classes was rejected because the package cannot prove they are disposable, nor can it safely infer the operational impact of removing them.

Re-running migrations on every outbox operation was rejected because migrations own broader convergence behavior and are not a per-request authority API. Runtime admission instead reads only the live catalogs required to prove the current index boundary.

## Verification

Migration regression continues to inspect `indexprs`, `indpred`, `indclass`, the index relation access method, `pg_opclass`, canonical unique-constraint ownership, and exact indexed table attribute types while keeping package/Docker migration bytes identical.

Runtime RED commit `51389a944465d36b70c8c4e6b527df2d5571e29a` added a structural requirement for live `pg_index`/`pg_opclass` admission plus a PostgreSQL specimen that attaches an expression index after container initialization. Its immutable function raises on one canonical event; after index creation, `EXECUTE` is revoked from `PUBLIC`, yet the specimen must still prove that the attached index can affect a runtime write before the application admission check is evaluated. The test-only CI run was canceled by the subsequent normal fast-forward production commit, so no hosted RED result is transferred from that canceled run.

Minimal production repair `84fcbfe82cb4e0e5b0452c570d0d56b29ec84e23` adds one `_unsafe_outbox_index_sql()` catalog predicate and invokes it before tenant binding/data SQL. Exact-head CI `34115708058` and Release Acceptance `34115708075` are terminal success. The PostgreSQL/container job passed the extended live table-program smoke, proving the post-migration index specimen is detected, while the structural suite passed on Python 3.10/3.12/3.14. This ADR remains Proposed until the stack integrates normally through the protected branch.

## Consequences

Every outbox access now pays for live index-catalog verification in addition to the existing RLS and authority graph. Issue #307 must include `pg_index`, `pg_class`, `pg_opclass`, `pg_attribute`, `pg_constraint`, and key-position traversal in the complete-path latency profile; security checks may not be excluded to manufacture the p95 target.

The runtime guard is fail-closed and intentionally refuses post-migration index drift rather than repairing it. Operators must reconcile any noncanonical index explicitly, rerun the migration verifier where appropriate, and then reacquire runtime admission evidence.

The guard does not protect against a PostgreSQL superuser mutating catalogs concurrently after admission and before the following statement; superuser/catalog mutation remains outside the ordinary tenant-isolation guarantee. Privileged DDL must remain operationally separated from application traffic.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 11.7. Indexes on expressions*. https://www.postgresql.org/docs/18/indexes-expressional.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE INDEX*. https://www.postgresql.org/docs/18/sql-createindex.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 36.16. Interfacing extensions to indexes*. https://www.postgresql.org/docs/18/xindex.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE OPERATOR CLASS*. https://www.postgresql.org/docs/18/sql-createopclass.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.26. pg_index*. https://www.postgresql.org/docs/18/catalog-pg-index.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.33. pg_opclass*. https://www.postgresql.org/docs/18/catalog-pg-opclass.html
