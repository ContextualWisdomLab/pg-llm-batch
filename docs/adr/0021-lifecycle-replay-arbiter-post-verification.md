# ADR 0021: Post-verify the lifecycle replay arbiter

- Status: Proposed
- Date: 2026-09-06
- Owners: `pg-llm-batch` lifecycle persistence bounded context

## Problem

`PostgresContextLifecycleOutboxStore` uses `ON CONFLICT (tenant_scope, evidence_id) DO NOTHING` as its durable replay/idempotency boundary. Migration 0008 already converged `uq_llm_context_lifecycle_outbox_tenant_evidence` to a validated, nondeferrable `UNIQUE (tenant_scope, evidence_id)` constraint when the installed catalog state was missing or noncanonical. The migration did not, however, read the catalog again after `ALTER TABLE ... ADD CONSTRAINT`. A successful DDL return was therefore treated as sufficient evidence that the replay arbiter was still canonical at migration completion.

That evidence model was weaker than the lifecycle UUID default, canonical CHECK, RLS policy, and operational-index paths, which converge and then verify the resulting authority before reporting migration success. A DDL hook, extension, restore-time automation, or privileged concurrent administrative mechanism can alter catalog state after the repair DDL completes but before the migration's later work finishes. Migration success must not certify replay safety when its runtime `ON CONFLICT` arbiter is no longer present in the reviewed shape.

## Constraints

The repair must preserve the existing aggregate and runtime contract, including exact tenant/evidence key order, nondeferrability, validation state, package/Docker migration byte identity, and idempotent reapplication. It must not rewrite durable rows, introduce a second idempotency key, weaken RLS, or claim protection against a PostgreSQL superuser that can mutate state after migration completion. The repair also must remain inside migration 0008 rather than moving replay authority into another service or mutable sibling dependency.

## Alternatives considered

Keeping successful `ADD CONSTRAINT` return as sufficient evidence was rejected because migration success is used as schema-readiness evidence and the surrounding lifecycle authorities already use converge-then-verify semantics.

Verifying only that a same-name constraint exists was rejected because a same-name deferrable constraint, a different key order, or a different constraint type is not a valid arbiter for the package's exact `ON CONFLICT (tenant_scope, evidence_id)` contract.

Recreating the UNIQUE constraint unconditionally on every migration was rejected because it adds unnecessary DDL, validation, and lock cost to already-converged installations.

Moving replay identity into application memory or another service was rejected because the PostgreSQL outbox owns durable replay identity and the transaction containing durable lifecycle intent must retain the database-level uniqueness invariant.

## Decision

Migration 0008 repeats the same `pg_constraint` admission predicate immediately after the repair block. The post-repair verifier requires the package-owned name, `contype = 'u'`, `convalidated`, `NOT condeferrable`, and exact `conkey` order for `tenant_scope` followed by `evidence_id`. Failure raises the fixed error `lifecycle outbox replay arbiter failed canonical verification`, causing the atomic migration statement to roll back rather than certifying a noncanonical replay boundary.

The package migration and Docker initializer are updated to the identical SQL blob `01802478dae9b27b9104c980e6f7a89ef9e666c5` at causal fix `f5dbe0e63390bc73f496d9acf96c2c94131f27c6`.

Static RED `98b691be778d9eb095b57456f81b94c004748b3f` requires the exact admission predicate to repeat after `ADD CONSTRAINT` and requires the fixed fail-closed error after that second read. Executable acceptance `6456509beb462351eea3a7bd7cd46f10baf4509f` extends the wired PostgreSQL container smoke with a superuser-only `ddl_command_end` event trigger. The test removes the canonical replay arbiter, lets migration 0008 add it, renames it immediately after the `ALTER TABLE` command completes, proves the sabotage ran through a PostgreSQL server-log marker, requires migration failure and transactional rollback, removes the test-only trigger/function, and then requires a clean migration reapplication to restore the canonical arbiter.

## Risks and limits

The repeated catalog predicate intentionally duplicates a short authority check. A future change to the replay-arbiter shape must update both predicates together; the static regression exists to make divergence visible. The event-trigger acceptance requires PostgreSQL superuser authority only in the isolated test container and is not production installation behavior.

Post-verification establishes catalog state at the point the migration checks it. It does not prevent a privileged administrator, extension, or later migration from changing the constraint afterward. Production role separation, migration provenance, protected deployment procedures, and runtime failure handling remain separate controls.

## Effect

A successful migration no longer infers replay safety from successful repair DDL alone. The lifecycle outbox certifies the same validated, nondeferrable `(tenant_scope, evidence_id)` arbiter before and after convergence, matching the database authority required by the runtime conflict target. Already-current installations do not incur replacement DDL.

Hosted exact-head PostgreSQL/container execution is still required before this repair is called GREEN or the ADR can move from Proposed to Accepted.

## Follow-up

Keep `docs/product-technical-gap-baseline.md`, `CHANGELOG.md`, the PR exact-head evidence, and the wired PostgreSQL smoke synchronized with this decision. Before merge, require exact-head CI/Release Acceptance, the predecessor stack's protected-merge conditions, and two fresh immutable-release/dependency sweeps. Do not transfer GREEN from superseded heads.

## References

PostgreSQL Global Development Group. (2026a). *Constraints*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-constraints.html

PostgreSQL Global Development Group. (2026b). *INSERT*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026c). *pg_constraint*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html

PostgreSQL Global Development Group. (2026d). *Event triggers*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/event-triggers.html
