# ADR 0025: Lifecycle Outbox Index-Program Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch

## Context

`public.llm_context_lifecycle_outbox` is the pg-llm-batch durability boundary for tenant-scoped lifecycle publication intent. Migration 0009 already rejected unknown CHECK/FK/PK/UNIQUE/EXCLUDE constraints and standalone UNIQUE indexes, then added rejection for non-unique expression and partial indexes.

That still left one executable index-program path. PostgreSQL records the operator class chosen for every index key in `pg_index.indclass`. An operator class defines the index semantics for a data type/access-method pair and supplies index support functions. PostgreSQL explicitly notes that index machinery invokes those functions without checking function execute privileges. A user-defined operator class can therefore execute operator-selected code while maintaining an otherwise plain, non-unique column index even when `indexprs` and `indpred` are both NULL. Its support function can raise and reject an otherwise canonical lifecycle event.

The active container target remains PostgreSQL 16, while PostgreSQL 18 documentation is used as the latest primary catalog/interface reference. The relevant `pg_index.indclass`, `pg_opclass`, and operator-class support-function semantics are compatible with the target contract exercised by the container smoke.

## Decision

Migration 0009 fails closed when any index attached to the lifecycle outbox has either `pg_index.indexprs IS NOT NULL` or `pg_index.indpred IS NOT NULL`, regardless of uniqueness.

For every simple index key, migration 0009 additionally requires the selected operator class to:

- belong to `pg_catalog`;
- be the default operator class for the exact indexed column type;
- belong to the same access method as the index relation; and
- match the table attribute type recorded for that key position.

This rejects user-defined/custom operator-class support functions without unnecessarily banning PostgreSQL-core simple-column indexes. In particular, a non-unique built-in hash index using PostgreSQL's default `pg_catalog` operator class remains admissible. Standalone UNIQUE indexes remain rejected unless `pg_constraint.conindid` proves that they back the exact canonical primary key or `(tenant_scope, evidence_id)` replay constraint.

The application isolation contract already excludes arbitrary superuser/catalog mutation from tenant authority. This decision therefore treats the default `pg_catalog` operator-class identity as PostgreSQL-core authority rather than trying to defend against a database superuser replacing core catalog objects.

Unknown expression, partial, unique-arbiter, or custom-opclass indexes are not auto-dropped. Their function dependencies, performance role, retention consequences, and ownership require explicit operator reconciliation.

Package migration 0009 and its Docker initializer are required to remain byte-identical. A change to one copy without the other is a release-blocking mirror defect.

## Alternatives rejected

Allowing non-unique expression indexes was rejected because uniqueness is not the only way an index can alter write acceptance: expression evaluation itself occurs on writes and can fail.

Allowing partial indexes solely because their predicate is not a uniqueness arbiter was rejected because the predicate is executable catalog state selected outside the package-owned lifecycle contract.

Treating every plain non-unique column index as inert was rejected because the selected operator class supplies support functions that index maintenance can execute even when the key is a direct column reference.

Restricting all allowed indexes to btree was rejected as broader than the causal boundary. A PostgreSQL-core non-unique hash index with the default `pg_catalog` operator class does not introduce operator-selected support-function authority and remains an ordinary operational index choice.

Allow-listing function names was rejected because name identity does not prove function body, dependency, language, or ownership identity and would introduce another mutable authority surface.

Automatically dropping unknown indexes or operator classes was rejected because the package cannot prove they are disposable, nor can it safely infer the operational impact of removing them.

## Verification

Static regression requires migration 0009 to inspect `indexprs`, `indpred`, `indclass`, the index relation access method, `pg_opclass`, and the exact indexed table attribute type while keeping package/Docker migration bytes identical.

The wired PostgreSQL container smoke retains the expression-index specimen and adds two operator-class cases:

1. a simple non-unique built-in hash index must remain admissible; and
2. a plain btree column index using a custom operator class whose comparison support function raises for one canonical event must demonstrably reject that write, after which migration 0009 must reject the custom operator class with the fixed content-free row-admission authority error.

After explicit operator-style removal, migration reapplication must succeed. Hosted exact-head PostgreSQL execution is required before this ADR may move to Accepted.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 36.16. Interfacing extensions to indexes*. https://www.postgresql.org/docs/18/xindex.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: CREATE OPERATOR CLASS*. https://www.postgresql.org/docs/18/sql-createopclass.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.26. pg_index*. https://www.postgresql.org/docs/18/catalog-pg-index.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.33. pg_opclass*. https://www.postgresql.org/docs/18/catalog-pg-opclass.html
