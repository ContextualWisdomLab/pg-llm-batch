# Product / Technical Gap Baseline

This document records commercial-development gaps owned by `pg-llm-batch` or materially gating its release. It is a code-current decision/evidence ledger, not a substitute for live PR, check, review, release, or protected-ref reads.

The active Context Fabric consumer-readiness stack retains PostgreSQL-backed durable lifecycle intent, tenant/RLS isolation, replay identity, and provider-neutral `BatchInferencePort` ownership in this repository. Mutable sibling heads are candidate evidence only; production integration may consume compatible immutable released contracts through a pg-owned anti-corruption layer.

## Canonical product boundary

`pg-llm-batch` owns durable/asynchronous LLM batch preparation, token/size accounting, provider-neutral batch lifecycle ports, PostgreSQL persistence, tenant/RLS isolation, recovery evidence, result ingestion, and the local outbox used to commit privacy-minimized lifecycle publication intent with product state.

Provider/model discovery, routing, fallback, and credentials remain outside this bounded context. Context Graph / Context Fabric integration may consume only compatible immutable released contracts. Mutable sibling branches, source copies, and cross-service SQL are not production authority. PR #323 separately owns the commercial PostgreSQL driver migration, including shared database-driver code; this stack does not overwrite that lane.

## Current gaps and disposition

| Gap | State | Current evidence / next condition |
| --- | --- | --- |
| Existing lifecycle-outbox table could contain undeclared additive columns | Repaired on active Draft; hosted GREEN pending | RED `76c5b0001d178625275ee8c16afbca5b7720b70a` adds a real PostgreSQL specimen that appends `undeclared_payload` and requires migration failure. Causal fix `f12e9b220ca4e2a32d6f0d6e4254251796eb06d2` requires exactly the 14 package-owned live user columns before later constraint/index repair; `47542d6e826bfbec88981c346782b4384d2918ab` restores package/Docker byte parity and `d84c2af4276ddc80b5827855e0a565a2b87c0bf1` pins the exact-column-set static contract. This prevents a stale/manual additive column from becoming undeclared durable data or PII authority. Exact-head PostgreSQL/container execution remains required before GREEN is claimed. |
| Existing table could drift in required column type/nullability/default/generated/identity/PK semantics | Repaired on active Draft; hosted GREEN pending | Migration 0008 inspects `pg_attribute`, `pg_attrdef`, and `pg_constraint` after `CREATE TABLE IF NOT EXISTS`, validates all required columns, canonical runtime defaults, generated/identity status, and a validated nondeferrable PK on `context_outbox_uuid`, then fails closed before constraint/index repair on mismatch. |
| Lifecycle-outbox runtime/migration object resolution inherited caller `search_path` | Repaired on active Draft | Runtime uses `pg_catalog.set_config` and `public.llm_context_lifecycle_outbox` without mutating caller transaction search state. Installer creation targets `public` explicitly while the installer-owned path remains `pg_catalog, public, pg_temp`. |
| Caller-controlled row-lock mode accepted arbitrary truthy values | Repaired on active Draft | RED `c6c03c4667d0d4f61f6fade694d84e87c6c4e0b4`; fix `c77ad8895634d96a5da86288e48cb843241f1a6f` requires exact built-in `bool` before tenant binding or SQL. |
| Lifecycle-outbox store exposed admitted PostgreSQL DSN | Repaired on active Draft | RED `34010cdb4267afafd7e06246b29cf7765403cae3`; fix `ed081bbe21deb49938d32895c6b6eab267d94cf0` keeps the exact DSN package-internal and removes the public accessor. |
| Canonical RLS policy name could mask policy drift or additional widening policy | Repaired on active Draft | Migration verifies command, permissive mode, PUBLIC role, both stored expressions, rejects unknown policy names, and verifies canonical v2 before retiring known predecessors. Policy predicates bind equality and `current_setting` through `pg_catalog`. |
| Existing-table `CREATE TABLE IF NOT EXISTS` could skip payload grammar/integrity CHECKs | Repaired on active Draft; hosted GREEN pending | RED `5fb675259311f8f9ec9e1f5142ad1992ec1f2915`; fix `221c86571ca5142586d75e75c67f257a127c1189` adds validated inheritable canonical payload CHECK v1; `5d1ddd22034af2ba71eddeea0107113bec78abd4` binds its comment stamp to a reproducible SHA-256 of the reviewed grammar. |
| Legacy package payload CHECKs could survive beside canonical v1 and keep stale stricter semantics authoritative | Repaired on active Draft; hosted GREEN pending | RED `93a9752bf806b41be4aa43c5aa40195da5b9b3cb` requires all ten known pre-canonical payload CHECK names to retire only after canonical v1 exists. Causal SQL fix `b32dcd0a89bb831e04980a10728793fe8c3105f2` removes those package-owned predecessor constraints in both byte-identical package and Docker migration copies. `eff4efa7a3679a5e94fed6f35f5b2ff3671db50e` extends the already-wired PostgreSQL container smoke: it restores an intentionally stricter legacy `event_type` CHECK, reapplies migration, and requires that predecessor constraint to disappear. Unknown constraint names are not deleted by this repair. |
| Canonical UTC timestamp CHECK name could mask noncanonical state | Repaired on active Draft | Canonical checks require validated inheritable CHECK state plus package semantic stamps; stale same-name constraints are rebuilt once. |
| Existing table could lack the nondeferrable `(tenant_scope, evidence_id)` replay arbiter | Repaired on active Draft | RED `939b5ae55f42c63205e9b86618272fcfecca4791`; migration converges a validated nondeferrable UNIQUE with exact `conkey` order. Runtime `ON CONFLICT (tenant_scope, evidence_id) DO NOTHING` therefore has a schema-level arbiter after successful migration. |
| Same-name operational index could have the wrong key order or unusable catalog state | Repaired on active Draft; hosted GREEN pending | Static RED `e7174cfe11874ef815dc53bd0d48af3cc2cf0d3e`, executable PostgreSQL specimen `338a1ddb753b0fb03d1e8de5643d28a550f32f44`, and tightened fail-closed contract `e5e4db86cd1d5348056c248f3b9600e27120f3e7` require the public valid/ready/live nonunique two-key B-tree over exactly `(tenant_scope, created_at)` with no expression or predicate. |
| Exact-head executable evidence for active #319 stack | Waiting on hosted runner | CI and Release Acceptance must execute against the final exact head. Predecessor or superseded-head GREEN is not transferable. |
| Dependency root #233 | Protected merge prerequisite | Re-read exact head, required checks, CodeQL compatibility evidence, independent reviews, and unresolved threads before merge. Do not self-approve or weaken gates. |
| Immutable Context Graph / enterprise architecture / orchestrator authority | Blocked until compatible immutable releases exist | Re-read tag, source commit, artifact digest, provenance, schema/profile, admission, and conformance identities before any production binding. Mutable PR heads remain candidate evidence only. |
| Commercial PostgreSQL driver migration | Separate active writer | PR #323 owns that slice. No overlapping rewrite or destructive restack from this lane. |
| Release package / SBOM / provenance / rollback proof | Not yet releasable | Perform only after the exact protected head is merge-ready and owner gates are terminal green. Version, CHANGELOG, tag, package, immutable release, SBOM, provenance, reproducibility, and rollback evidence must identify the same source. |
| Buyer-path p95 ≤ 20 ms | Unproven for this slice | Do not infer the threshold from unit tests or warm-cache microbenchmarks. Measure applicable PostgreSQL/API paths with realistic/right-cleared data and full connection lifecycle once hosted/runtime execution is available. |

## Integrity decision trace: exact durable outbox row shape

**Problem.** `CREATE TABLE IF NOT EXISTS` can leave an existing relation in place. The structural admission guard already rejected missing or incompatible required columns, but a stale or manually altered table could still carry an additional live user column. PostgreSQL would then accept migration success even though the durable aggregate had acquired state outside the package-owned schema. An undeclared nullable column may look harmless to current SQL, but it creates an ungoverned persistence surface for future code, restore tooling, manual operations, or sensitive data.

**Constraints.** Preserve existing canonical rows, transactionality, package/Docker migration parity, and idempotent reapplication. Do not auto-drop an unknown column because the package cannot prove its legal or operational disposal semantics. Do not relax the existing required-column, default, PK, RLS, CHECK, UNIQUE, or index guards.

**Alternatives.** Ignoring additive columns was rejected because the outbox is the canonical durability boundary and purpose-bound data minimization requires the stored shape itself to be explicit. Automatically dropping unknown columns was rejected as destructive and potentially irreversible. Maintaining a second allow-list outside migration SQL was rejected because it would create another mutable schema authority.

**Decision.** Migration 0008 now requires exactly 14 live positive-numbered, non-dropped user columns after proving the 14 named expected columns and their structural properties. Because both conditions must hold, the check detects both missing/incompatible required columns and unexpected additive columns. Any mismatch raises the existing fixed `lifecycle outbox structural schema mismatch` error before later constraint/index repair.

RED `76c5b0001d178625275ee8c16afbca5b7720b70a` modifies a real PostgreSQL table with an `undeclared_payload` column and requires reapplication to fail. Causal SQL fix `f12e9b220ca4e2a32d6f0d6e4254251796eb06d2` adds the exact live-column-count invariant; `47542d6e826bfbec88981c346782b4384d2918ab` mirrors the same SQL bytes into the container initializer; `d84c2af4276ddc80b5827855e0a565a2b87c0bf1` adds a static regression so the catalog contract cannot silently disappear when no integration database is available.

**Effect.** Successful migration now admits only the package-declared durable row shape rather than an arbitrary structural superset. This is a schema/data-authority guarantee, not proof that a privileged database administrator cannot mutate the database. It also does not justify deleting unknown production data; mismatch remains a fail-closed operator repair condition. Hosted exact-head PostgreSQL execution is required before this repair is called GREEN.

## Integrity decision trace: lifecycle payload CHECK convergence

**Problem.** Migration 0008 originally put tenant scope, event/evidence identity, digest, and truth-status CHECKs only inside `CREATE TABLE IF NOT EXISTS`. PostgreSQL documents that `IF NOT EXISTS` suppresses the duplicate-relation error but does not guarantee the existing relation resembles the requested definition. A restored, manually repaired, or stale installation could therefore lack one or more payload constraints while the migration continued successfully. A second convergence defect remained after canonical payload v1 was introduced: the ten earlier package-owned CHECKs could coexist with canonical v1. If a restore or operator had changed one predecessor to a stricter predicate, valid current payloads could still be rejected even though canonical v1 was installed successfully.

**Constraints.** Preserve rows accepted by the reviewed current grammar, avoid deleting unknown operator-owned constraints, keep package and Docker SQL byte-identical, and avoid repeated heavyweight DDL after a store has converged. The migration may retire only package-owned predecessor names whose semantics have been superseded by canonical v1.

**Alternatives.** Leaving the predecessor checks in place was rejected because multiple simultaneous package grammar authorities prevent deterministic convergence. Dropping every noncanonical CHECK was rejected because an unknown constraint can encode operator or application invariants outside this migration's authority. Rewriting the table was rejected as unnecessary and more disruptive.

**Decision.** Migration 0008 first establishes `ck_llm_context_lifecycle_outbox_payload_canonical_v1`, then conditionally drops exactly the ten known pre-canonical package CHECK names. Once absent, ordinary reapplication performs no payload-predecessor DDL. The aggregate v1 remains the package grammar authority; unknown CHECK names are left intact rather than being silently destroyed.

RED `93a9752bf806b41be4aa43c5aa40195da5b9b3cb` pins the required predecessor-retirement order. Causal SQL fix `b32dcd0a89bb831e04980a10728793fe8c3105f2` applies that order to the package and Docker copies with one shared blob. Executable acceptance `eff4efa7a3679a5e94fed6f35f5b2ff3671db50e` uses a real PostgreSQL container, adds a stale package-named `event_type = 'legacy.only'` predecessor after canonical initialization, reapplies migration, and requires that stale predecessor to be gone.

**Effect.** A successful converged migration has one package-owned payload grammar generation instead of canonical v1 plus residual predecessor semantics. The repair does not claim ownership of arbitrary third-party CHECK constraints and does not remove them. Exact-head hosted PostgreSQL execution remains required before GREEN is claimed.

## Reliability/performance decision trace: lifecycle operational-index convergence

**Problem.** Name-only `CREATE INDEX IF NOT EXISTS` does not establish index identity. A restored or manually altered database could retain the canonical name on the wrong key order, a partial/expression index, an invalid index, or another unusable shape.

**Decision.** Migration admits the operational index only when PostgreSQL catalog state proves the target relation, `public` namespace, B-tree access method, valid/ready/live state, nonunique two-key shape, no expression/predicate, and exact `(tenant_scope, created_at)` key order. A same-name index on the target relation that fails the contract is rebuilt once; an unrelated same-name relation fails closed.

**Effect.** Successful migration establishes the tenant-first operational index shape rather than merely its name. This removes one source of restore/migration latency drift but does not prove the buyer-path p95 target.

## Release gate

A release is incomplete while any runnable merge, fix, test, restack, review/thread, owner-path, documentation-to-code, or buyer-gap action remains. Before release, perform two fresh live sweeps and require the exact protected head, required checks, review state, security evidence, immutable dependency identities, and release artifacts to agree. Routine status reporting is not completion evidence.

## References

PostgreSQL Global Development Group. (2026a). *Schemas*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-schemas.html

PostgreSQL Global Development Group. (2026b). *pg_policy*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026c). *System information functions and operators*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026d). *CREATE POLICY*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026e). *pg_constraint*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html

PostgreSQL Global Development Group. (2026f). *INSERT*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026g). *CREATE TABLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026h). *CREATE INDEX*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-createindex.html

PostgreSQL Global Development Group. (2026i). *pg_index*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-index.html

PostgreSQL Global Development Group. (2026j). *ALTER TABLE*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/sql-altertable.html

PostgreSQL Global Development Group. (2026k). *pg_attribute*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/catalog-pg-attribute.html
