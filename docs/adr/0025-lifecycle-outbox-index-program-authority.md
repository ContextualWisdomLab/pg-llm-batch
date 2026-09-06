# ADR 0025: Lifecycle Outbox Index-Program Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch

## Context

`public.llm_context_lifecycle_outbox` is the pg-llm-batch durability boundary for tenant-scoped lifecycle publication intent. Migration 0009 already rejected unknown CHECK/FK/PK/UNIQUE/EXCLUDE constraints and standalone UNIQUE indexes, but it admitted non-unique expression and partial indexes.

That distinction is not sufficient for an authority boundary. PostgreSQL computes index expressions for each row insertion and non-HOT update. Partial indexes also carry a stored predicate. An operator-selected immutable function used by either form can still raise an exception and reject an otherwise canonical lifecycle event. The index therefore becomes executable write-time authority even when it does not enforce uniqueness.

The active PostgreSQL container target is PostgreSQL 16. The decision uses the PostgreSQL 16 catalog contract (`pg_index.indexprs`, `pg_index.indpred`) and remains compatible with later catalog documentation.

## Decision

Migration 0009 fails closed when any index attached to the lifecycle outbox has either `pg_index.indexprs IS NOT NULL` or `pg_index.indpred IS NOT NULL`, regardless of uniqueness.

Simple non-unique column indexes remain permitted because they do not add a row predicate or operator-selected expression. Standalone UNIQUE indexes remain rejected unless `pg_constraint.conindid` proves that they back the exact canonical primary key or `(tenant_scope, evidence_id)` replay constraint.

Unknown expression or partial indexes are not auto-dropped. Their function dependencies, performance role, retention consequences, and ownership require explicit operator reconciliation.

Package migration 0009 and its Docker initializer are required to remain byte-identical. A change to one copy without the other is a release-blocking mirror defect.

## Alternatives rejected

Allowing non-unique expression indexes was rejected because uniqueness is not the only way an index can alter write acceptance: expression evaluation itself occurs on writes and can fail.

Allowing partial indexes solely because their predicate is not a uniqueness arbiter was rejected because the predicate is executable catalog state selected outside the package-owned lifecycle contract.

Allow-listing function names was rejected because name identity does not prove function body, dependency, language, or ownership identity and would introduce another mutable authority surface.

Automatically dropping unknown indexes was rejected because the package cannot prove they are disposable, nor can it safely infer the operational impact of removing them.

## Verification

Static regression requires migration 0009 to inspect both `indexprs` and `indpred`. The wired PostgreSQL container smoke installs a non-unique expression index whose `IMMUTABLE` PL/pgSQL function raises for an otherwise canonical event, proves that the index can reject the write, and requires migration 0009 to reject the index with the fixed content-free authority error. After explicit operator-style removal, migration reapplication must succeed.

Hosted exact-head PostgreSQL execution is required before this ADR may move to Accepted.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: 11.7. Indexes on expressions*. https://www.postgresql.org/docs/16/indexes-expressional.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: 11.8. Partial indexes*. https://www.postgresql.org/docs/16/indexes-partial.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: 53.26. pg_index*. https://www.postgresql.org/docs/16/catalog-pg-index.html
