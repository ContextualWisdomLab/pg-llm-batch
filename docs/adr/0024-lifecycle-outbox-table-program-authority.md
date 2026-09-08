# ADR 0024: Lifecycle Outbox Table-Program and Relation Authority

- Status: Proposed
- Date: 2026-09-06
- Updated: 2026-09-08

## Context

`public.llm_context_lifecycle_outbox` is the package-owned durable boundary for privacy-minimized lifecycle publication intent. Migration 0008 admits one ordinary logged table with an exact row shape, no inheritance edges, canonical constraints, forced tenant RLS, and a verified operational index. Those checks also reject executable programs attached to the table.

PostgreSQL records table triggers in `pg_trigger`; `tgrelid` identifies the relation, `tgfoid` identifies the function called, and `tgisinternal` distinguishes internally generated triggers from ordinary user triggers. PostgreSQL records query-rewrite rules in `pg_rewrite`; `ev_class` identifies the table or view to which a rule belongs. A user trigger or rewrite rule can therefore intercept, suppress, supplement, redirect, or reject lifecycle writes while columns, constraints, indexes, RLS, and the application role remain otherwise canonical.

Migration 0008 is the convergence owner. Migration 0009 is the final row-admission verifier. Runtime `_require_rls_application_role()` re-proves the mutable table-program, schema, constraint/default, RLS, role/delegation, view/materialized/foreign, callable-authority, and relation boundary before tenant binding or durable data SQL. A catalog proof is not transferable to later I/O when either table-program authority or qualified-name resolution can change after that proof.

Three concrete temporal gaps define this decision.

1. **Admission to write program authority.** A table owner can wait until live admission returns safe, install a trigger or other conflicting relation DDL, commit it, and affect the subsequent `INSERT` unless the write path retains a conflicting table lock across admission and the write.
2. **Admission to read relation object.** A table owner can wait until live admission returns safe, rename or replace the admitted relation, and make the later `SELECT` resolve a relation object the catalog proof never admitted unless the read path pulls its relation lock ahead of admission.
3. **Namespace-name rebinding despite a retained relation lock.** `ACCESS SHARE` retains the admitted relation *object* against conflicting relation DDL, but the schema object named `public` is independently mutable. A schema owner can rename the original `public` schema, create a new `public` schema, and create another `public.llm_context_lifecycle_outbox` while the original relation remains locked. A later qualified reference can then bind by name to a different relation OID. Relation-object locking and namespace/name identity are therefore separate authorities.

PostgreSQL table locks are the database-native relation-object fence. `INSERT` normally acquires `ROW EXCLUSIVE`; ordinary `SELECT` acquires `ACCESS SHARE`; explicit table locks are normally retained until transaction end. PostgreSQL object identifiers provide the durable database-local identity needed to distinguish two same-named relations. `pg_class.oid` identifies the relation object, `pg_class.relnamespace` independently identifies its namespace, `regclass`/`to_regclass()` resolve names to relation OIDs, and the `tableoid` system column identifies the table object from which a returned row originated.

## Decision

Convergence, final migration admission, and every runtime outbox admission treat table-attached programs and exact relation-object identity as security authority. Qualified names remain useful addressing syntax but are not accepted as object identity by themselves.

Migration 0008 rejects any `pg_trigger` row on the lifecycle outbox for which `tgisinternal` is false and rejects any `pg_rewrite` row whose `ev_class` is the lifecycle outbox before later convergence. Migration 0009 independently repeats those catalog checks and fails closed if either topology exists after 0008. Runtime `_require_rls_application_role()` independently performs the full live catalog proof before tenant `set_config` or outbox data SQL and returns the exact validated lifecycle-outbox `pg_class.oid` together with its role-safety verdict.

### Write path

`PostgresContextLifecycleOutboxStore.enqueue_in_transaction()` acquires

```sql
LOCK TABLE ONLY public.llm_context_lifecycle_outbox IN ROW EXCLUSIVE MODE
```

before live authority admission. The caller-owned transaction retains that lock through tenant binding, replay arbitration, and the durable write. This pulls forward the normal modifying-DML relation lock so conflicting table-program or relation DDL cannot become effective between proof and write.

The lock is not sufficient evidence that the later qualified name still denotes the admitted relation. The admitted OID is therefore carried into one data-modifying SQL statement. A CTE resolves the then-live qualified name with `pg_catalog.to_regclass('public.llm_context_lifecycle_outbox')::oid`; the `INSERT ... SELECT` executes only when that live OID equals the admitted OID. Namespace rebinding therefore yields zero inserted rows and the store fails closed instead of treating the forged same-name relation as admitted authority.

The identity comparison must remain in the statement that conditionally performs the write. A standalone `to_regclass()` recheck followed by a separate `INSERT` would merely create another temporal gap.

### Read path

`PostgresContextLifecycleOutboxStore.load_in_transaction()` acquires

```sql
LOCK TABLE ONLY public.llm_context_lifecycle_outbox IN ACCESS SHARE MODE
```

before live authority admission. The caller-owned transaction retains that lock through tenant binding, optional tenant/event advisory serialization, and the consuming read. This is intentionally the same table-lock mode an ordinary `SELECT` would acquire, pulled ahead of the catalog proof. It protects the admitted relation object without widening ordinary reads to a write-strength lock.

The consuming read also proves name-to-object identity in the same SQL statement that can return evidence. It resolves the then-live qualified name to an OID and requires that OID to equal the admitted OID. Any returned durable row must additionally have `tableoid = admitted_oid`. If the namespace/name was rebound after admission, the identity predicate fails and no application evidence is accepted from the forged same-name relation.

The read fence does not change the API meaning of `for_update`: same-tenant/event compare-and-swap serialization continues to use a transaction-scoped advisory lock rather than `SELECT ... FOR UPDATE`, so the ordinary runtime role does not need ambient `UPDATE` authority. The advisory lock is not a substitute for the table lock or relation-OID proof because PostgreSQL schema DDL does not participate in the package advisory-lock key space and an advisory key does not authenticate a catalog object.

PostgreSQL-internal constraint triggers remain admitted because they can represent database-managed constraint machinery already governed by the reviewed constraint contract. Neither migrations nor runtime automatically delete or rewrite unknown triggers, rules, relations, schemas, or other authority-bearing objects. Ownership and side effects cannot be inferred safely; reconciliation remains explicit operator work followed by fresh admission.

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

- executable specimen `de11c351a9814ad37f09ace9f4f46048f8f46023` creates an ordinary outbox owner and ordinary `NOSUPERUSER NOBYPASSRLS` runtime role, then attempts `CREATE TRIGGER` from a second connection immediately after runtime admission returns safe;
- CI wiring `302b82fdb8642504534392f9c6414674ca131c2d` produced hosted RED in CI `34158620631` at `Run lifecycle-outbox admission-to-write race authority smoke`;
- causal production fix `c80dac22303dcf92b423797a638b646e822d6d00` pulls `ROW EXCLUSIVE` acquisition ahead of live admission without changing RLS, tenant semantics, migrations, or replay identity; and
- exact production-fix CI `34159401347` and Release Acceptance `34159401351` completed successfully.

Owner-contract RED `6a496cdc9af069c08d22e729158ce4d9aabc63ea`, CI `34159677365`, then required AGENTS, CLAUDE, and this ADR to retain the `ROW EXCLUSIVE` admission-to-write boundary.

The initial admission-to-read repair established the relation-object fence:

- executable PostgreSQL specimen `a55285dd52d47a5208706ce424672a716433b341` created an ordinary owner and read-only runtime principal, waited until live admission returned safe, then attempted to rename the admitted outbox and install a forged same-name replacement before the later read;
- exact RED head `28f9ccfc096ff018bcea060ee86c557940ebc6f8` produced hosted RED in CI `34173601154`, PostgreSQL/container job `101898554640`;
- causal production fix `9ad1565f5c5e9f6009d7b046779e0ccf65158cb5` pulled `ACCESS SHARE` acquisition ahead of live admission; and
- descendant unit contract `b20b32e0ff0d99cd286628a1b2d1ccbe89172a91` required the lock to precede catalog admission for both ordinary and serialized reads without introducing a row-update lock.

That relation-lock repair exposed the remaining namespace authority gap. Hosted predecessor `e6e55aed9dc9b21f29f252ebc1ee71b03f4fbf22` renamed schema `public`, recreated `public` and a forged same-name outbox while the original relation remained locked, and then demonstrated that a later qualified read could resolve the unadmitted object. CI `34175295889`, PostgreSQL/container job `101903418145`, failed with `AssertionError: runtime did not retain public-schema identity through SELECT`.

Causal production repair `1d42227b5e09de5c25c329579303271c8335d1d4` changed the authority token from an implicit qualified name to the exact admitted relation OID and bound both consuming paths to it. Descendants `ccbfccdd7689d808847538cd8bb19d9344ba9ebb`, `73830f7502227232c9daf4b16e394ddcd2b4879e`, `0383b2ce443a5db50ebbd5da66204163c8bfbaee`, `191adef3901beab1f1288995601f3be4e5df87ca`, `c4ade302c06345a9c7a0bc9edae6d2bb8ed8cf4e`, and `8ea31ac2dd762f4dcb2d90a5d1d98154345fda9b` aligned the realistic PostgreSQL and unit fixtures with the three-field admission result and both read/write rebinding paths.

Exact `8ea31ac2dd762f4dcb2d90a5d1d98154345fda9b` then exposed a test-contract coverage RED rather than a production regression. CI `34181443723` ran 1659 passing tests and a successful PostgreSQL/container lane, while the 100% coverage gate identified three no-longer-exercised defensive branches: both invalid-shape guards in `_evidence_from_row()` and exact-boolean `for_update` validation in `_load_in_transaction_with_relation_oid()`.

Test-only repair `f02ad256740108c2dfd31c2bfbc040a02d2e8169` restores those edge contracts without changing production source. Exact-head CI `34181944316` completed successfully with 1665 passed, 7 deselected, 4279/4279 production statements, 1146/1146 branches, public docstrings 100%, Ruff, lockfile, and package build all passing. Its PostgreSQL/container lane also completed the relation rebinding and the full authority-smoke chain successfully. Exact-head Release Acceptance `34181944315` completed successfully after building two clean source trees and verifying wheel/sdist artifact identity.

This ADR update follows that exact source/test GREEN. Its own descendant head must reacquire exact-head CI and Release Acceptance; the predecessor results above are provenance, not transferable acceptance.

This ADR remains Proposed until the protected integration path completes normally.

## Alternatives considered

**Rely on the later `SELECT` to acquire `ACCESS SHARE`.** Rejected. PostgreSQL would acquire the right relation lock class only when the data statement begins, after the earlier admission statement has already left a DDL interleaving window.

**Treat the pre-admission table lock as complete namespace authority.** Rejected. A lock on the admitted relation object does not lock the independently renameable schema object or prove that a later qualified name still resolves to that relation OID.

**Run a standalone `to_regclass()` identity recheck before data SQL.** Rejected. A separate recheck followed by a separate consuming statement creates another TOCTOU interval. The OID equality must participate in the SQL statement that can return durable evidence or perform the write.

**Re-run admission after data SQL.** Rejected. On reads it is too late to retract evidence returned from an unadmitted object; on writes a trigger/rule or forged relation may already have observed or changed durable state.

**Use `ROW EXCLUSIVE` for reads.** Rejected. It is unnecessarily broad for the admitted relation-object fence and still does not authenticate the independently mutable namespace/name binding.

**Use `ACCESS EXCLUSIVE` to pin everything.** Rejected. It would unnecessarily serialize ordinary application traffic, and broadening the relation lock is not a principled substitute for authenticating the exact object consumed.

**Pin caller `search_path` or depend on schema qualification.** Rejected. The query is already schema-qualified; the defect is that the schema/name can be rebound to a different OID. Search-path restrictions do not prove object identity.

**Use only the package advisory lock.** Rejected because it serializes cooperative replay participants by tenant/event key but neither conflicts with PostgreSQL schema DDL nor authenticates catalog objects.

**Allow triggers/rules or replacement relations as extension points.** Rejected because lifecycle durability and tenant isolation would then depend on executable or schema authority outside the aggregate contract. Name allow-lists are insufficient because names are not object identity.

Migration-only detection remains insufficient because migration history is not current catalog evidence after restore or later privileged administration. Runtime-only detection remains insufficient for installation readiness. The selected design therefore proves topology at convergence, at final migration admission, at live runtime admission, and retains both the admitted relation-object lock and the exact admitted OID through the consuming read or write.

## Consequences

Reads can wait behind concurrent relation DDL holding or awaiting incompatible table locks. Writes already carry the corresponding `ROW EXCLUSIVE` wait. Namespace DDL can also make the live qualified-name OID proof fail even when the originally admitted relation object remains valid. These outcomes are intentional fail-closed behavior; bypassing either boundary would reopen the authority TOCTOU.

Ordinary application concurrency remains materially preserved. `ACCESS SHARE` does not conflict with normal `SELECT`, `INSERT`, `UPDATE`, or `DELETE` table locks; `ROW EXCLUSIVE` remains compatible with other ordinary modifying DML at the table-lock level. The OID proof adds catalog/name-resolution work to each admitted I/O rather than a broad serialization lock.

Issue #307 must include connection acquisition, explicit lock acquisition/wait, admitted-OID and live namespace/name identity proof, complete live catalog/role/definer/view/materialized/foreign/default/constraint admission, tenant binding, data I/O, and cleanup in the same buyer-path p50/p95/p99 evidence. Catalog cardinality, connection pressure, and schema-DDL contention must be varied. The OID/security work may not be excluded, sampled away, or hidden behind an unrealistic warm-cache-only setup to manufacture p95 <= 20 ms.

Explicit locking adds normal deadlock and lock-ordering considerations. Callers that combine domain-table work with outbox operations must use a stable transaction ordering and treat PostgreSQL deadlock/lock-timeout failures as transaction failures rather than weakening the fence or retrying only the outbox sub-operation.

The change does not add cross-service SQL, provider coupling, prompt/response storage, mutable upstream dependencies, or new publication authority. It narrows only the pg-llm-batch-owned lifecycle persistence boundary.

## References

PostgreSQL Global Development Group. (2026a). *PostgreSQL 18 documentation: Explicit locking*. https://www.postgresql.org/docs/18/explicit-locking.html

PostgreSQL Global Development Group. (2026b). *PostgreSQL 18 documentation: LOCK*. https://www.postgresql.org/docs/18/sql-lock.html

PostgreSQL Global Development Group. (2026c). *PostgreSQL 18 documentation: Object identifier types*. https://www.postgresql.org/docs/18/datatype-oid.html

PostgreSQL Global Development Group. (2026d). *PostgreSQL 18 documentation: pg_class*. https://www.postgresql.org/docs/18/catalog-pg-class.html

PostgreSQL Global Development Group. (2026e). *PostgreSQL 18 documentation: System columns*. https://www.postgresql.org/docs/18/ddl-system-columns.html

PostgreSQL Global Development Group. (2026f). *PostgreSQL 18 documentation: pg_trigger*. https://www.postgresql.org/docs/18/catalog-pg-trigger.html

PostgreSQL Global Development Group. (2026g). *PostgreSQL 18 documentation: pg_rewrite*. https://www.postgresql.org/docs/18/catalog-pg-rewrite.html

PostgreSQL Global Development Group. (2026h). *PostgreSQL 18 documentation: Overview of trigger behavior*. https://www.postgresql.org/docs/18/trigger-definition.html