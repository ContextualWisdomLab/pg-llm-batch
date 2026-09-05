# ADR 0024: Lifecycle Outbox Table-Program Authority

- Status: Proposed
- Date: 2026-09-06

## Context

`public.llm_context_lifecycle_outbox` is the package-owned durable boundary for privacy-minimized lifecycle publication intent. Migration 0008 already admits one ordinary logged table with an exact row shape, no inheritance edges, canonical constraints, forced tenant RLS, and a verified operational index. Those checks did not cover executable programs attached to the table.

PostgreSQL records table triggers in `pg_trigger`; `tgrelid` identifies the relation and `tgisinternal` distinguishes internally generated triggers from ordinary user triggers. PostgreSQL records query-rewrite rules in `pg_rewrite`; rules attached to a table can rewrite commands before normal table execution. An added user trigger or rewrite rule can therefore intercept, supplement, suppress, redirect, or otherwise change lifecycle writes while every previously checked column, constraint, policy, and index remains canonical (PostgreSQL Global Development Group, 2026a, 2026b).

## Decision

Migration 0008 treats executable table programs as structural authority. Before CHECK/RLS/UNIQUE/index convergence it rejects any `pg_trigger` row on the lifecycle outbox for which `tgisinternal` is false, and rejects any `pg_rewrite` row whose `ev_class` is the lifecycle outbox.

The migration does not automatically drop an unknown trigger, trigger function, or rewrite rule. Their ownership, side effects, retention implications, and external dependencies cannot be inferred safely from the package schema, so production reconciliation is an explicit operator action. PostgreSQL-internal triggers are not rejected by this rule because they can represent database-managed constraint machinery rather than an unreviewed application program.

Static RED `281adf515293e2aea296fbc48f48cb6316065691` requires both catalog guards. Executable RED `eb6f82546b390b7a39cdb9220939f1179914b62e` installs a no-op user trigger and a no-op `DO ALSO` rewrite rule on a real PostgreSQL outbox and requires migration to fail with the fixed structural-schema error for each specimen. Causal fix `15cc5dc889741c8adc25c45e04b8d3b98982a110` adds the guards and atomically points the package migration and Docker initializer at identical SQL blob `9b9e6e0391a5f10ab2e5becbce68cf9ff76be9fa`.

## Alternatives considered

Allowing triggers or rules as an extension point was rejected because it would make lifecycle durability and tenant isolation depend on executable database programs outside the aggregate contract. Allow-listing program names was rejected because a name is not executable identity and would require function/rule definition, owner, dependency, security-definer, and search-path authority to become a second migration contract. Automatically deleting unknown programs was rejected as destructive. Runtime-only detection was rejected because migration success itself is used as schema-readiness evidence and Docker/package installation must converge on the same boundary.

## Consequences

A migration success can now be used as evidence that ordinary outbox I/O is not intercepted by a user trigger or rewrite rule at validation time. This does not protect against a privileged database administrator adding a program after migration, nor does it establish hosted GREEN until the exact-head PostgreSQL/container acceptance executes. Operators that intentionally require table programs must first make a separate reviewed architecture decision rather than attaching them silently to this canonical relation.

## References

PostgreSQL Global Development Group. (2026a). *pg_trigger*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-trigger.html

PostgreSQL Global Development Group. (2026b). *pg_rewrite*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-rewrite.html
