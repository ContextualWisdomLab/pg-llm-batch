# ADR 0024: Lifecycle Outbox Table-Program Authority

- Status: Proposed
- Date: 2026-09-06

## Context

`public.llm_context_lifecycle_outbox` is the package-owned durable boundary for privacy-minimized lifecycle publication intent. Migration 0008 admits one ordinary logged table with an exact row shape, no inheritance edges, canonical constraints, forced tenant RLS, and a verified operational index. Those checks also reject executable programs attached to the table.

PostgreSQL records table triggers in `pg_trigger`; `tgrelid` identifies the relation, `tgfoid` identifies the function called, and `tgisinternal` distinguishes internally generated triggers from ordinary user triggers. PostgreSQL records query-rewrite rules in `pg_rewrite`; `ev_class` identifies the table or view to which a rule belongs. A user trigger or rewrite rule can therefore intercept, suppress, supplement, redirect, or reject lifecycle writes while columns, constraints, indexes, and RLS remain canonical (PostgreSQL Global Development Group, 2026a, 2026b, 2026c).

Migration 0008 is the convergence owner. Migration 0009 is the final row-admission verifier. Fresh review found that the original 0009 re-proved final RLS, canonical CHECK predicates, constraint identity, and index/operator-class authority, but did not independently re-read `pg_trigger` or `pg_rewrite`. A restore or manual DDL operation performed after 0008 had been recorded as applied could therefore attach table programs and still pass the final admission gate.

## Decision

Both convergence and final admission treat table-attached programs as executable authority.

Migration 0008 rejects any `pg_trigger` row on the lifecycle outbox for which `tgisinternal` is false and rejects any `pg_rewrite` row whose `ev_class` is the lifecycle outbox before later convergence.

Migration 0009 independently repeats those two catalog checks. It fails closed if any user trigger or rewrite rule exists, even when migration 0008 was previously applied successfully. PostgreSQL-internal constraint triggers remain admitted because they can represent database-managed constraint machinery already governed by the reviewed constraint contract.

Neither migration automatically drops an unknown trigger, trigger function, or rewrite rule. Their ownership, side effects, retention implications, and external dependencies cannot be inferred safely from the package schema. Production reconciliation is therefore an explicit operator action followed by fresh final admission.

Package and Docker copies of migration 0009 remain byte-identical.

## Verification lineage

The original convergence work remains:

- static RED `281adf515293e2aea296fbc48f48cb6316065691` requiring migration 0008 to inspect `pg_trigger` and `pg_rewrite`;
- executable RED `eb6f82546b390b7a39cdb9220939f1179914b62e` installing a no-op user trigger and `DO ALSO` rewrite rule on a real PostgreSQL outbox;
- causal fix `15cc5dc889741c8adc25c45e04b8d3b98982a110`, with package/Docker migration 0008 at identical blob `9b9e6e0391a5f10ab2e5becbce68cf9ff76be9fa`.

The final-admission repair adds a distinct replay-after-convergence specimen:

- static RED `121c3f9e100a5ec11e4ddd885753e23b8d97376c` requires migration 0009 itself to inspect both catalogs;
- executable PostgreSQL RED `e6ab6525ca6eaf5d6b175280c4e3a94fa7d865bf` installs a `BEFORE INSERT` trigger whose function raises on an otherwise canonical lifecycle event, then installs an `INSTEAD NOTHING` rewrite rule that suppresses an otherwise canonical insert; migration 0009 must reject each topology;
- causal fix `31e819938a1fbb4a704d2756f1727caf93198571` adds the final catalog verifier to both package and Docker migration 0009 without moving convergence authority out of 0008.

This ADR remains Proposed until hosted exact-head PostgreSQL/container acceptance executes these final-admission specimens. Queued or predecessor runs are not transferable evidence.

## Alternatives considered

Allowing triggers or rules as an extension point was rejected because it would make lifecycle durability and tenant isolation depend on executable database programs outside the aggregate contract. Allow-listing program names was rejected because a name is not executable identity and would require function/rule definition, owner, dependency, security-definer, and search-path authority to become a second migration contract. Automatically deleting unknown programs was rejected as destructive. Runtime-only detection was rejected because migration success itself is schema-readiness evidence and Docker/package installation must converge on the same boundary. Relying only on migration 0008 was rejected because migration history is not current catalog evidence after restore or manual DDL.

## Consequences

Successful migration 0008 establishes the canonical topology at convergence time; successful migration 0009 re-proves that no user trigger or rewrite rule has become final row-admission authority since then. Operators that intentionally require table programs must make a separate reviewed architecture decision rather than attaching them silently to this canonical relation.

This does not protect against a privileged administrator modifying the database after final admission, nor does it treat PostgreSQL superuser/catalog mutation as part of the ordinary tenant-isolation guarantee. Production application roles remain `NOSUPERUSER NOBYPASSRLS`.

## References

PostgreSQL Global Development Group. (2026a). *pg_trigger*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-trigger.html

PostgreSQL Global Development Group. (2026b). *pg_rewrite*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-rewrite.html

PostgreSQL Global Development Group. (2026c). *Overview of trigger behavior*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/trigger-definition.html
