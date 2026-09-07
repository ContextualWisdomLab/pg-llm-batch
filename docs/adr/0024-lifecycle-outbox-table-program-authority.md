# ADR 0024: Lifecycle Outbox Table-Program Authority

- Status: Proposed
- Date: 2026-09-06
- Updated: 2026-09-07

## Context

`public.llm_context_lifecycle_outbox` is the package-owned durable boundary for privacy-minimized lifecycle publication intent. Migration 0008 admits one ordinary logged table with an exact row shape, no inheritance edges, canonical constraints, forced tenant RLS, and a verified operational index. Those checks also reject executable programs attached to the table.

PostgreSQL records table triggers in `pg_trigger`; `tgrelid` identifies the relation, `tgfoid` identifies the function called, and `tgisinternal` distinguishes internally generated triggers from ordinary user triggers. PostgreSQL records query-rewrite rules in `pg_rewrite`; `ev_class` identifies the table or view to which a rule belongs. A user trigger or rewrite rule can therefore intercept, suppress, supplement, redirect, or reject lifecycle writes while columns, constraints, indexes, RLS, and the application role remain otherwise canonical (PostgreSQL Global Development Group, 2026a, 2026b, 2026c).

Migration 0008 is the convergence owner. Migration 0009 is the final row-admission verifier. Earlier review found that the original 0009 re-proved final RLS, canonical CHECK predicates, constraint identity, and index/operator-class authority, but did not independently re-read `pg_trigger` or `pg_rewrite`. That was repaired so restore or manual DDL performed after 0008 cannot pass final migration admission with an attached table program.

Fresh runtime review found a second temporal gap. A privileged operator can attach a user trigger or rewrite rule after both migrations have succeeded and later remove the role capability that installed it. `_require_rls_application_role()` already re-proves mutable RLS policy, ACL, membership, role, `SECURITY DEFINER`, view, materialized-copy, inheritance/partition, and foreign-data authority before tenant binding and durable data SQL, but it did not re-read the canonical outbox's own `pg_trigger` or `pg_rewrite` rows. The migration receipt therefore remained point-in-time evidence while a persistent attached program could become current write authority.

## Decision

Convergence, final migration admission, and every runtime outbox admission treat table-attached programs as executable authority.

Migration 0008 rejects any `pg_trigger` row on the lifecycle outbox for which `tgisinternal` is false and rejects any `pg_rewrite` row whose `ev_class` is the lifecycle outbox before later convergence. Migration 0009 independently repeats those two catalog checks and fails closed if either topology exists after 0008.

Runtime `_require_rls_application_role()` now independently performs the same live catalog boundary before tenant `set_config` or outbox data SQL. It rejects any non-internal trigger whose `tgrelid` is the admitted outbox and any rewrite rule whose `ev_class` is the admitted outbox. This remains intentionally conservative: the application role does not need arbitrary attached trigger/rule extension points, and a prior migration success does not authorize later DDL drift.

PostgreSQL-internal constraint triggers remain admitted because they can represent database-managed constraint machinery already governed by the reviewed constraint contract. The runtime does not infer safety from the identity that originally created an attached program, from the current runtime role's inability to create another one, or from a later revocation of `TRIGGER`/DDL authority. The persistent catalog object itself is current executable authority.

Neither migrations nor runtime automatically drop an unknown trigger, trigger function, or rewrite rule. Their ownership, side effects, retention implications, and external dependencies cannot be inferred safely from the package schema. Production reconciliation remains an explicit operator action followed by fresh admission.

Package and Docker copies of migration 0009 remain byte-identical; the runtime repair does not move migration ownership or alter the schema contract.

## Verification lineage

The original convergence work remains:

- static RED `281adf515293e2aea296fbc48f48cb6316065691` requiring migration 0008 to inspect `pg_trigger` and `pg_rewrite`;
- executable RED `eb6f82546b390b7a39cdb9220939f1179914b62e` installing a no-op user trigger and `DO ALSO` rewrite rule on a real PostgreSQL outbox;
- causal fix `15cc5dc889741c8adc25c45e04b8d3b98982a110`, with package/Docker migration 0008 at identical blob `9b9e6e0391a5f10ab2e5becbce68cf9ff76be9fa`.

The final-migration repair remains:

- static RED `121c3f9e100a5ec11e4ddd885753e23b8d97376c` requiring migration 0009 itself to inspect both catalogs;
- executable PostgreSQL RED `e6ab6525ca6eaf5d6b175280c4e3a94fa7d865bf` installing a `BEFORE INSERT` trigger whose function raises on an otherwise canonical lifecycle event, then an `INSTEAD NOTHING` rewrite rule that suppresses an otherwise canonical insert;
- causal fix `31e819938a1fbb4a704d2756f1727caf93198571` adding the final catalog verifier to both package and Docker migration 0009 without moving convergence authority out of 0008.

The live-runtime repair adds a distinct post-migration specimen:

- RED tests `b560c71c7b2cd348074aec511839fd1d401e142c` and `f95e1a8d13366022bafc16fdb021cc9d8e62a1f4` require runtime admission to re-read both catalogs and construct a real PostgreSQL trigger/rule drift specimen after initialization;
- exact hosted head `4823cae6f3d5198c6094c8e55f8e235551d9dae6`, CI `34109490188`, failed structurally with `1 failed, 1628 passed, 7 deselected` because `_require_rls_application_role()` did not contain the live `pg_trigger`/`pg_rewrite` probes;
- causal production fix `ed74f30d699772e4b48d9b404f77fa336616acfc` adds only the two live catalog existence checks before the existing policy/role authority graph. It does not weaken RLS, role traversal, tenant binding, migration behavior, data SQL, or workflow gates.

This ADR remains Proposed until a fresh exact head containing the production repair, runtime PostgreSQL specimen, owner instructions, and this ADR has terminal hosted CI/Release Acceptance evidence and later integrates normally through the protected branch. Queued, canceled, or predecessor runs are not transferable evidence.

## Alternatives considered

Allowing triggers or rules as an extension point was rejected because it would make lifecycle durability and tenant isolation depend on executable database programs outside the aggregate contract. Allow-listing program names was rejected because a name is not executable identity and would require function/rule definition, owner, dependency, security-definer, and search-path authority to become a second runtime contract. Automatically deleting unknown programs was rejected as destructive.

Migration-only detection was rejected because migration history is not current catalog evidence after restore, manual DDL, or later privileged administration. Runtime-only detection remains insufficient by itself because migration success is schema-readiness evidence and Docker/package installation must converge on the same boundary. The selected design therefore proves the same invariant at convergence, final migration admission, and live application admission.

Relying on the current runtime role's missing `TRIGGER` privilege was rejected because attached programs persist after privilege revocation and continue to execute or rewrite statements. Re-running migrations on every application operation was rejected because the migrations own broader convergence behavior and are not a per-request admission API; the live guard instead reads only the relevant catalogs as part of the existing authority query.

## Consequences

Successful migration 0008 establishes the canonical topology at convergence time; successful migration 0009 re-proves that no user trigger or rewrite rule has become final row-admission authority since then. Every runtime outbox access now re-proves the same attached-program absence before tenant binding and durable row access, alongside the existing live role/RLS/definer/view/materialized/foreign authority checks.

This adds two catalog existence probes to the package-owned admission path. Performance acceptance therefore must include those probes rather than excluding them as security overhead. Issue #307 remains the owner for realistic complete-path p95 measurement; this ADR does not claim the p95 target has been met.

The guard does not protect against a PostgreSQL superuser mutating catalogs concurrently after admission and before the following statement; superuser/catalog mutation is outside the ordinary tenant-isolation guarantee. Production application roles remain `NOSUPERUSER NOBYPASSRLS`, and privileged DDL must remain operationally separated from application traffic.

## References

PostgreSQL Global Development Group. (2026a). *pg_trigger*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-trigger.html

PostgreSQL Global Development Group. (2026b). *pg_rewrite*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-rewrite.html

PostgreSQL Global Development Group. (2026c). *Overview of trigger behavior*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/trigger-definition.html
