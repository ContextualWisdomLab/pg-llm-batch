# ADR 0024: Lifecycle Outbox Table-Program and Relation Authority

- Status: Proposed
- Date: 2026-09-06
- Updated: 2026-09-08

## Context

`public.llm_context_lifecycle_outbox` is the package-owned durable boundary for privacy-minimized lifecycle publication intent. Migration 0008 admits one ordinary logged table with an exact row shape, no inheritance edges, canonical constraints, forced tenant RLS, and a verified operational index. Those checks also reject executable programs attached to the table.

PostgreSQL records table triggers in `pg_trigger`; `tgrelid` identifies the relation, `tgfoid` identifies the function called, and `tgisinternal` distinguishes internally generated triggers from ordinary user triggers. PostgreSQL records query-rewrite rules in `pg_rewrite`; `ev_class` identifies the table or view to which a rule belongs. A user trigger or rewrite rule can therefore intercept, suppress, supplement, redirect, or reject lifecycle writes while columns, constraints, indexes, RLS, and the application role remain otherwise canonical.

Migration 0008 is the convergence owner. Migration 0009 is the final row-admission verifier. Runtime `_require_rls_application_role()` re-proves the mutable table-program, schema, constraint/default, RLS, role/delegation, view/materialized/foreign, and callable-authority boundary before tenant binding or durable data SQL. A catalog proof by itself is not enough, however, when the relation name can resolve to a different object after that proof.

Two concrete temporal gaps exist:

1. **Admission to write.** A table owner can wait until live admission returns safe, install a trigger or other conflicting DDL, commit it, and affect the subsequent `INSERT` unless the write path retains a conflicting table lock across admission and the write.
2. **Admission to read.** A schema-capable table owner can wait until live admission returns safe, rename the admitted relation, create another relation at `public.llm_context_lifecycle_outbox`, grant the runtime role `SELECT`, and commit before the later `SELECT` acquires its ordinary relation lock. The consuming statement can then resolve a relation object that the catalog proof never admitted. This is a relation-identity TOCTOU defect even when the query remains schema-qualified and uses `ONLY`.

PostgreSQL table locks provide the database-native fence. `INSERT` normally acquires `ROW EXCLUSIVE`. Ordinary `SELECT` acquires `ACCESS SHARE`. `ACCESS SHARE` conflicts only with `ACCESS EXCLUSIVE`, while `ROW EXCLUSIVE` also conflicts with the stronger schema/programming lock modes relevant to write mutation. Explicit locks are normally held until transaction end. Operations such as relation rename, replacement, or drop require `ACCESS EXCLUSIVE`; acquiring the read lock before admission therefore keeps the admitted relation identity stable through the consuming read without granting ownership, `MAINTAIN`, or write privilege.

## Decision

Convergence, final migration admission, and every runtime outbox admission treat table-attached programs and the admitted relation identity as security authority.

Migration 0008 rejects any `pg_trigger` row on the lifecycle outbox for which `tgisinternal` is false and rejects any `pg_rewrite` row whose `ev_class` is the lifecycle outbox before later convergence. Migration 0009 independently repeats those catalog checks and fails closed if either topology exists after 0008. Runtime `_require_rls_application_role()` independently performs the live catalog proof before tenant `set_config` or outbox data SQL.

### Write path

`PostgresContextLifecycleOutboxStore.enqueue_in_transaction()` acquires

```sql
LOCK TABLE ONLY public.llm_context_lifecycle_outbox IN ROW EXCLUSIVE MODE
```

before invoking live authority admission. The lock is retained by the caller-owned transaction through tenant binding, replay arbitration, and the durable `INSERT`. This pulls forward the normal modifying-DML relation lock so a conflicting table-program or schema DDL change cannot become effective between proof and write.

### Read path

`PostgresContextLifecycleOutboxStore.load_in_transaction()` acquires

```sql
LOCK TABLE ONLY public.llm_context_lifecycle_outbox IN ACCESS SHARE MODE
```

before invoking live authority admission. The lock is retained through tenant binding, the optional tenant/event advisory lock used for compare-and-swap semantics, and the consuming `SELECT`. This is intentionally the same table-lock mode an ordinary `SELECT` would eventually acquire, but it is acquired *before* the catalog proof rather than after it. Concurrent ordinary reads and writes remain compatible, while concurrent DDL requiring `ACCESS EXCLUSIVE` cannot rename, replace, drop, or otherwise swap the relation identity between admission and consumption.

The read fence does not change the API meaning of `for_update`: the store still uses a transaction-scoped advisory lock for same-tenant/event replay serialization instead of `SELECT ... FOR UPDATE`, so the ordinary runtime role does not need ambient `UPDATE` authority. The advisory lock is not a substitute for either table lock because PostgreSQL schema DDL does not participate in the package's advisory-lock key space.

PostgreSQL-internal constraint triggers remain admitted because they can represent database-managed constraint machinery already governed by the reviewed constraint contract. Neither migrations nor runtime automatically delete or rewrite unknown triggers, rules, relations, or schema objects. Their ownership and side effects cannot be inferred safely; reconciliation remains explicit operator work followed by fresh admission.

The normal application role remains limited to the intended non-grantable DML surface. The selected fences must not be widened to `ACCESS EXCLUSIVE`, and no `MAINTAIN`, ownership, `TRIGGER`, generic DDL, or new cross-service authority is added to application credentials.

## Verification lineage

The original table-program convergence remains:

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

The admission-to-write concurrency repair remains:

- executable specimen `de11c351a9814ad37f09ace9f4f46048f8f46023` creates an ordinary outbox owner and ordinary `NOSUPERUSER NOBYPASSRLS` runtime role, then attempts `CREATE TRIGGER` from a second connection immediately after the runtime has returned a safe live-admission result;
- CI wiring `302b82fdb8642504534392f9c6414674ca131c2d` produced hosted RED in CI `34158620631` at `Run lifecycle-outbox admission-to-write race authority smoke`;
- causal production fix `c80dac22303dcf92b423797a638b646e822d6d00` pulls `ROW EXCLUSIVE` acquisition ahead of live admission without changing RLS, tenant semantics, migrations, or replay identity; and
- exact production-fix CI `34159401347` and Release Acceptance `34159401351` completed successfully.

Owner-contract RED `6a496cdc9af069c08d22e729158ce4d9aabc63ea`, CI `34159677365`, then required AGENTS, CLAUDE, and this ADR to retain the `ROW EXCLUSIVE` admission-to-write boundary.

The admission-to-read relation-identity repair extends the same bounded decision:

- executable PostgreSQL specimen `a55285dd52d47a5208706ce424672a716433b341` creates an ordinary owner and an ordinary read-only runtime principal, waits until live admission returns `(False, False)`, then tries to rename the admitted outbox and install a forged same-name replacement relation before the runtime read;
- CI wiring / exact RED head `28f9ccfc096ff018bcea060ee86c557940ebc6f8` produced hosted RED in CI `34173601154`, PostgreSQL/container job `101898554640`, where the new smoke failed with `AssertionError: runtime did not retain read-schema authority through SELECT`;
- causal production fix `9ad1565f5c5e9f6009d7b046779e0ccf65158cb5` pulls `ACCESS SHARE` acquisition ahead of live admission; and
- descendant unit-contract commit `b20b32e0ff0d99cd286628a1b2d1ccbe89172a91` requires the lock to precede catalog admission for both ordinary and compare-and-swap reads without introducing a row-update lock.

Exact-current hosted GREEN evidence is recorded on the PR after the final descendant head completes. Predecessor or canceled workflow state is not transferable evidence.

This ADR remains Proposed until the protected integration path completes normally.

## Alternatives considered

**Rely on the later `SELECT` to acquire `ACCESS SHARE`.** Rejected. PostgreSQL would acquire the right lock class, but only when the data statement begins, after the earlier admission statement has already released its statement-level snapshot and left a DDL interleaving window.

**Re-run catalog admission after the data statement.** Rejected. On reads it is too late to retract data consumed from an unadmitted replacement relation; on writes a trigger or rewrite rule may already have executed side effects, suppressed the insert, or failed the transaction.

**Use `ROW EXCLUSIVE` for reads as well.** Rejected. It is unnecessarily broad for relation-identity stability. `ACCESS SHARE` is sufficient to conflict with the `ACCESS EXCLUSIVE` DDL needed to rename, replace, or drop the relation while remaining compatible with normal reads and writes.

**Use only the package advisory lock.** Rejected because it serializes cooperative replay participants by tenant/event key but does not conflict with PostgreSQL table DDL.

**Use `ACCESS EXCLUSIVE` for either path.** Rejected because it would unnecessarily serialize normal application traffic and provide no security benefit beyond the minimal lock modes required for the demonstrated races.

**Allow triggers/rules or replacement relations as extension points.** Rejected because lifecycle durability and tenant isolation would then depend on executable or schema authority outside the aggregate contract. Name allow-lists are insufficient because names are not object identity.

Migration-only detection remains insufficient because migration history is not current catalog evidence after restore or later privileged administration. Runtime-only detection remains insufficient for installation readiness. The selected design therefore proves topology at convergence, at final migration admission, at live runtime admission, and retains the admitted relation authority until the consuming read or write has executed in the same transaction.

## Consequences

Reads can now wait behind concurrent schema DDL holding or awaiting incompatible relation locks. Writes already had the corresponding `ROW EXCLUSIVE` wait. These waits are intentional: bypassing them would reopen the authority TOCTOU.

Ordinary application concurrency remains materially preserved. `ACCESS SHARE` does not conflict with normal `SELECT`, `INSERT`, `UPDATE`, or `DELETE` table locks; `ROW EXCLUSIVE` remains compatible with other ordinary modifying DML at the table-lock level.

Issue #307 must include both explicit lock acquisition/wait paths in complete buyer-path performance evidence together with connection acquisition, live catalog/role/definer/view/materialized/foreign/default/constraint admission, tenant binding, data I/O, and cleanup. DDL contention and security admission may not be excluded to manufacture the p95 target.

Explicit locking adds normal deadlock and lock-ordering considerations. Callers that combine domain-table work with outbox operations must use a stable transaction ordering and treat PostgreSQL deadlock/lock-timeout failures as transaction failures rather than weakening the fence or retrying only the outbox sub-operation.

The change does not add cross-service SQL, provider coupling, prompt/response storage, mutable upstream dependencies, or new publication authority. It narrows only the pg-llm-batch-owned lifecycle persistence boundary.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: Explicit locking*. https://www.postgresql.org/docs/18/explicit-locking.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: LOCK*. https://www.postgresql.org/docs/18/sql-lock.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: pg_trigger*. https://www.postgresql.org/docs/18/catalog-pg-trigger.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: pg_rewrite*. https://www.postgresql.org/docs/18/catalog-pg-rewrite.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: Overview of trigger behavior*. https://www.postgresql.org/docs/18/trigger-definition.html
