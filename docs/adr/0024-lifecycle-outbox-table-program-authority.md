# ADR 0024: Lifecycle Outbox Table-Program Authority

- Status: Proposed
- Date: 2026-09-06
- Updated: 2026-09-08

## Context

`public.llm_context_lifecycle_outbox` is the package-owned durable boundary for privacy-minimized lifecycle publication intent. Migration 0008 admits one ordinary logged table with an exact row shape, no inheritance edges, canonical constraints, forced tenant RLS, and a verified operational index. Those checks also reject executable programs attached to the table.

PostgreSQL records table triggers in `pg_trigger`; `tgrelid` identifies the relation, `tgfoid` identifies the function called, and `tgisinternal` distinguishes internally generated triggers from ordinary user triggers. PostgreSQL records query-rewrite rules in `pg_rewrite`; `ev_class` identifies the table or view to which a rule belongs. A user trigger or rewrite rule can therefore intercept, suppress, supplement, redirect, or reject lifecycle writes while columns, constraints, indexes, RLS, and the application role remain otherwise canonical.

Migration 0008 is the convergence owner. Migration 0009 is the final row-admission verifier. The earlier repair made 0009 re-read `pg_trigger` and `pg_rewrite`, and runtime `_require_rls_application_role()` subsequently re-proved the same mutable table-program boundary before tenant binding or durable data SQL. That still left a temporal gap: admission and the later write were separate statements. A table owner could wait until the runtime catalog query returned safe, then execute `CREATE TRIGGER`, commit it, and cause the following outbox `INSERT` to execute newly attached behavior. This is an admission-to-write TOCTOU defect, not merely a hypothetical direct system-catalog mutation by a superuser.

PostgreSQL's table-lock rules provide the matching database primitive. `INSERT` acquires `ROW EXCLUSIVE`; that mode conflicts with `SHARE`, `SHARE ROW EXCLUSIVE`, `EXCLUSIVE`, and `ACCESS EXCLUSIVE`. `CREATE TRIGGER` acquires `SHARE ROW EXCLUSIVE`. Explicit locks are normally retained until transaction end. PostgreSQL also permits a role with `INSERT` privilege to acquire `ROW EXCLUSIVE`, so closing the race does not require granting the runtime role `MAINTAIN`, ownership, or broader DDL authority.

## Decision

Convergence, final migration admission, and every runtime outbox admission treat table-attached programs as executable authority.

Migration 0008 rejects any `pg_trigger` row on the lifecycle outbox for which `tgisinternal` is false and rejects any `pg_rewrite` row whose `ev_class` is the lifecycle outbox before later convergence. Migration 0009 independently repeats those catalog checks and fails closed if either topology exists after 0008. Runtime `_require_rls_application_role()` independently performs the same live catalog boundary before tenant `set_config` or outbox data SQL.

The write path additionally fences schema authority across admission-to-write. `PostgresContextLifecycleOutboxStore.enqueue_in_transaction()` acquires

```sql
LOCK TABLE ONLY public.llm_context_lifecycle_outbox IN ROW EXCLUSIVE MODE
```

before calling the live authority admission path. The lock is retained by the caller-owned transaction through tenant binding, replay arbitration, and the durable `INSERT`. This deliberately pulls forward the same table-level lock class PostgreSQL would acquire for modifying DML. Concurrent application writes remain compatible with one another, while `CREATE TRIGGER` and other operations requiring a conflicting table lock cannot commit new executable write authority between the catalog proof and the write that consumes it.

Read-only `load()`/`load_in_transaction(..., for_update=False)` remain unchanged and do not acquire `ROW EXCLUSIVE`; the stronger fence is required only for a path that will write. The existing transaction-scoped advisory lock remains responsible for same-tenant/event replay serialization. It is not a substitute for the table lock because PostgreSQL schema DDL does not participate in the package's advisory-lock key space.

PostgreSQL-internal constraint triggers remain admitted because they can represent database-managed constraint machinery already governed by the reviewed constraint contract. Neither migrations nor runtime automatically drop an unknown trigger, trigger function, rewrite rule, or other schema object. Their ownership and side effects cannot be inferred safely; production reconciliation remains explicit operator work followed by fresh admission.

The normal application role remains limited to non-grantable `SELECT` and `INSERT`. The selected fence must not be widened to `ACCESS EXCLUSIVE`, and no `MAINTAIN`, ownership, `TRIGGER`, or generic DDL authority is added to application credentials.

## Verification lineage

The original convergence work remains:

- static RED `281adf515293e2aea296fbc48f48cb6316065691` requiring migration 0008 to inspect `pg_trigger` and `pg_rewrite`;
- executable RED `eb6f82546b390b7a39cdb9220939f1179914b62e` installing a no-op user trigger and `DO ALSO` rewrite rule on a real PostgreSQL outbox; and
- causal fix `15cc5dc889741c8adc25c45e04b8d3b98982a110`, with package/Docker migration 0008 at identical blob `9b9e6e0391a5f10ab2e5becbce68cf9ff76be9fa`.

The final-migration repair remains:

- static RED `121c3f9e100a5ec11e4ddd885753e23b8d97376c` requiring migration 0009 itself to inspect both catalogs;
- executable PostgreSQL RED `e6ab6525ca6eaf5d6b175280c4e3a94fa7d865bf` installing a `BEFORE INSERT` trigger whose function raises on an otherwise canonical lifecycle event, then an `INSTEAD NOTHING` rewrite rule that suppresses an otherwise canonical insert; and
- causal fix `31e819938a1fbb4a704d2756f1727caf93198571` adding the final catalog verifier to package and Docker migration 0009 without moving convergence authority out of 0008.

The live-runtime repair remains:

- RED tests `b560c71c7b2cd348074aec511839fd1d401e142c` and `f95e1a8d13366022bafc16fdb021cc9d8e62a1f4` requiring runtime admission to re-read both catalogs and construct a real PostgreSQL trigger/rule drift specimen after initialization;
- hosted RED head `4823cae6f3d5198c6094c8e55f8e235551d9dae6`, CI `34109490188`, with the structural runtime-table-program contract failing; and
- causal production fix `ed74f30d699772e4b48d9b404f77fa336616acfc` adding only the two live catalog existence checks before the existing policy/role authority graph.

The admission-to-write concurrency repair extends this same bounded decision:

- executable specimen `de11c351a9814ad37f09ace9f4f46048f8f46023` creates an ordinary outbox owner and ordinary `NOSUPERUSER NOBYPASSRLS` runtime role, then attempts `CREATE TRIGGER` from a second connection immediately after the runtime has returned a safe live-admission result;
- CI wiring `302b82fdb8642504534392f9c6414674ca131c2d` produced hosted RED in CI `34158620631`: the PostgreSQL container lane failed specifically at `Run lifecycle-outbox admission-to-write race authority smoke`, demonstrating that the hostile trigger could commit between admission and the subsequent insert;
- causal production fix `c80dac22303dcf92b423797a638b646e822d6d00` pulls `ROW EXCLUSIVE` acquisition ahead of live admission without changing RLS, tenant semantics, migrations, replay identity, or the read-only path; and
- exact production-fix CI `34159401347` and Release Acceptance `34159401351` both completed successfully, including the new PostgreSQL concurrency specimen and all existing container/runtime smokes.

Owner-contract RED `6a496cdc9af069c08d22e729158ce4d9aabc63ea`, CI `34159677365`, then required AGENTS, CLAUDE, and this ADR to retain the `ROW EXCLUSIVE` admission-to-write boundary; Python 3.14 failed as intended before the documentation repair.

This ADR remains Proposed until the protected integration path completes normally. Queued, canceled, predecessor, synthetic, or otherwise non-executed workflow state is not transferable GREEN evidence.

## Alternatives considered

Relying on a live catalog check immediately before the insert was rejected because two statements leave a DDL interleaving window. Rechecking after the insert was rejected because a trigger or rewrite rule may already have executed side effects, suppressed the write, or failed the transaction.

Using only the package advisory lock was rejected because it serializes cooperative replay participants by tenant/event key but does not conflict with PostgreSQL table DDL. Raising the fence to `ACCESS EXCLUSIVE` was rejected because it would unnecessarily block compatible reads and application DML. `ROW EXCLUSIVE` is sufficient for the demonstrated trigger race and is the lock mode PostgreSQL already associates with modifying DML.

Allowing triggers or rules as an extension point was rejected because lifecycle durability and tenant isolation would then depend on executable database programs outside the aggregate contract. Allow-listing program names was rejected because names are not executable identity and would require function/rule definition, owner, dependency, security-definer, and search-path authority to become another mutable runtime contract. Automatically deleting unknown programs was rejected as destructive.

Migration-only detection remains insufficient because migration history is not current catalog evidence after restore or later privileged administration. Runtime-only detection remains insufficient for installation readiness. The selected design therefore proves topology at convergence, at final migration admission, at live runtime admission, and—on the write path—holds conflicting DDL out until the consuming insert has executed within the same transaction.

## Consequences

A package write can now wait behind incompatible schema/maintenance work before live admission. That wait is intentional: allowing the write to race ahead with stale authority would invalidate the security proof. Ordinary concurrent outbox inserts remain compatible at the table-lock level because `ROW EXCLUSIVE` does not conflict with itself.

The explicit lock acquisition and any contention are part of complete buyer-path performance evidence. Issue #307 must include the lock wait together with connection acquisition, live catalog/role/definer/view/materialized/foreign/default/constraint admission, tenant binding, data I/O, and cleanup in p50/p95/p99 measurements. The p95 target is not satisfied by excluding DDL contention or security admission from the timed path.

Explicit locking adds normal deadlock and lock-ordering considerations. Callers that combine domain-table work with `enqueue_in_transaction()` must use a stable transaction ordering and treat PostgreSQL deadlock/lock-timeout failures as transaction failures rather than weakening the fence or retrying only the outbox sub-operation.

The change does not add cross-service SQL, provider coupling, prompt/response storage, mutable upstream dependencies, or new publication authority. It narrows only the pg-llm-batch-owned lifecycle persistence boundary.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: Explicit locking*. https://www.postgresql.org/docs/18/explicit-locking.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: LOCK*. https://www.postgresql.org/docs/18/sql-lock.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: pg_trigger*. https://www.postgresql.org/docs/18/catalog-pg-trigger.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: pg_rewrite*. https://www.postgresql.org/docs/18/catalog-pg-rewrite.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: Overview of trigger behavior*. https://www.postgresql.org/docs/18/trigger-definition.html
