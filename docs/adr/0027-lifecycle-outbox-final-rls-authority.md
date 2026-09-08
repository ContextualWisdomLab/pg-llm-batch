# ADR 0027: Lifecycle Outbox Final RLS Authority

- Status: Proposed
- Date: 2026-09-06
- Owners: pg-llm-batch

## Context

`public.llm_context_lifecycle_outbox` is the pg-llm-batch durability boundary for tenant-scoped lifecycle publication intent. Migration 0008 converges row-level security by enabling and forcing RLS and by converging one canonical all-command, permissive `PUBLIC` policy whose `USING` and `WITH CHECK` predicates bind `tenant_scope` to the transaction-local `pg_llm_batch.tenant_scope` setting. Migration 0009 is the final row-admission gate after that convergence.

Fresh review found that migration 0009 independently revalidated constraints and index programs but did not revalidate the relation-level RLS flags or policy semantics. That creates a restore/operator-drift gap after migration 0008 has already been recorded as applied. An operator can disable RLS while leaving the policy catalog row intact, or replace the canonical policy under the same name with `USING (true) WITH CHECK (true)`. Either state can expose rows across tenants to an otherwise ordinary `NOSUPERUSER NOBYPASSRLS` role while migration 0009 still reports success.

PostgreSQL documents that policies in `pg_policy` apply only when `pg_class.relrowsecurity` is set, and that disabling row security leaves policies defined but ignored. PostgreSQL also stores the policy command, permissive/restrictive mode, roles, `USING` expression tree, and `WITH CHECK` expression tree separately in `pg_policy`. A canonical policy name alone is therefore not final security authority.

The active container target remains PostgreSQL 16. PostgreSQL 16 documentation is used for the runtime behavior exercised by the container specimen; PostgreSQL 18 documentation is used as the latest primary catalog/interface reference and is materially consistent for these fields.

## Decision

Migration 0009 independently verifies final RLS authority before it evaluates CHECK, constraint, or index authority.

Admission requires all of the following:

- `pg_class.relrowsecurity` is true;
- `pg_class.relforcerowsecurity` is true;
- exactly one `pg_policy` row is attached to the lifecycle outbox;
- the policy has the exact canonical v2 name;
- it applies to all commands, is permissive, and applies to `PUBLIC`;
- `pg_get_expr(polqual, polrelid, false)` equals the canonical tenant predicate;
- `pg_get_expr(polwithcheck, polrelid, false)` equals the same canonical tenant predicate; and
- normal policy dependencies do not introduce a function or operator authority beyond `pg_catalog.current_setting(text, bool)` and PostgreSQL text equality.

Migration 0009 fails with the existing content-free `unexpected lifecycle outbox row-admission authority` error when any condition is false. It does not enable RLS, force RLS, replace a policy, or delete an unknown policy. Migration 0008 remains the single convergence owner; 0009 is a fail-closed final verifier.

Package migration 0009 and its Docker initializer must remain byte-identical.

## Alternatives rejected

Trusting the canonical policy name was rejected because the name does not encode the `USING` or `WITH CHECK` predicate and can survive a drop/recreate with different semantics.

Checking only that a policy exists was rejected because PostgreSQL explicitly ignores defined policies when row security is disabled.

Checking only `relrowsecurity` was rejected because the table owner normally bypasses RLS unless `FORCE ROW LEVEL SECURITY` is set, and the package contract already requires owner enforcement as part of the durable tenant boundary.

Allowing additional policies was rejected because permissive policies are combined with `OR`; an added permissive policy can widen visibility. The lifecycle outbox therefore keeps one reviewed policy authority.

Repairing policy drift in migration 0009 was rejected because migration 0008 already owns convergence. Duplicating repair authority would make migration order and audit evidence ambiguous.

## Verification

Static RED `058e0ff0f2f8411f62f3e0f8878103b864c2c904` requires migration 0009 to prove relation-level RLS flags plus canonical `pg_policy` command, mode, roles, and predicate identity.

Executable PostgreSQL RED specimen `529f96497ba3e3eb1f44c640ea202a7b68a52dae` creates a `NOSUPERUSER NOBYPASSRLS` probe role and two tenant rows. It first replaces the canonical policy under the same name with `USING (true) WITH CHECK (true)` and demonstrates that the tenant-a probe can see both rows; it then requires migration 0009 to reject that state. In a separate case it disables row-level security while retaining the canonical policy, demonstrates the same cross-tenant visibility, and again requires migration 0009 to reject the state. The specimen uses migration 0008 only to reconcile each deliberately drifted state before the next independent case.

CI wiring `40478e548cfd15d05e77af01481ad13ff0393b06` places that real PostgreSQL specimen in the existing container lane. Causal fix `eb07e48ecbddb3e4fb5a0dd72fc64ba7d3bf6e8a` adds final RLS verification to package migration 0009; `a72686cb41efe3f88462e9acbb9c962377a005d6` restores exact Docker/package migration identity.

Hosted exact-head PostgreSQL execution is required before this ADR may move to Accepted.

## References

PostgreSQL Global Development Group. (2026). *PostgreSQL 16 documentation: 5.8. Row security policies*. https://www.postgresql.org/docs/16/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 5.9. Row security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.11. pg_class*. https://www.postgresql.org/docs/18/catalog-pg-class.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: 52.38. pg_policy*. https://www.postgresql.org/docs/18/catalog-pg-policy.html
