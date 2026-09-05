# Product / Technical Gap Baseline

This document records commercial-development gaps owned by `pg-llm-batch` or
materially gating its release. It is a code-current decision/evidence ledger, not a
substitute for live PR, check, review, release, or protected-ref reads.

The active Context Fabric consumer-readiness stack retains PostgreSQL-backed durable
lifecycle intent, tenant/RLS isolation, replay identity, and provider-neutral
`BatchInferencePort` ownership in this repository. The latest migration repair series
is RED `5fb675259311f8f9ec9e1f5142ad1992ec1f2915`, causal convergence fix
`221c86571ca5142586d75e75c67f257a127c1189`, and reproducible semantic-stamp fix
`5d1ddd22034af2ba71eddeea0107113bec78abd4`; packaged migration 0008 and the
Docker initializer are byte-identical at blob
`a308bc7bb6c9719142c34e261717c1f3cd2f5564`.

## Canonical product boundary

`pg-llm-batch` owns durable/asynchronous LLM batch preparation, token/size
accounting, provider-neutral batch lifecycle ports, PostgreSQL persistence,
tenant/RLS isolation, recovery evidence, result ingestion, and the local outbox used
to commit privacy-minimized lifecycle publication intent with product state.

Provider/model discovery, routing, fallback, and credentials remain outside this
bounded context. Context Graph / Context Fabric integration may consume only
compatible immutable released contracts through a pg-owned anti-corruption layer.
Mutable sibling branches, source copies, and cross-service SQL are not production
authority. PR #323 separately owns the commercial PostgreSQL driver migration,
including shared database-driver code; this stack does not overwrite that lane.

## Current gaps and disposition

| Gap | State | Current evidence / next condition |
| --- | --- | --- |
| Lifecycle-outbox runtime/migration object resolution inherited caller `search_path` | Repaired on active Draft | Runtime uses `pg_catalog.set_config` and `public.llm_context_lifecycle_outbox` without mutating caller transaction search state. Installer creation targets `public` explicitly while the installer-owned path remains `pg_catalog, public, pg_temp`. Exact-head hosted execution remains required. |
| Caller-controlled row-lock mode accepted arbitrary truthy values | Repaired on active Draft | RED `c6c03c4667d0d4f61f6fade694d84e87c6c4e0b4`; fix `c77ad8895634d96a5da86288e48cb843241f1a6f` requires exact built-in `bool` before tenant binding or SQL. |
| Lifecycle-outbox store exposed admitted PostgreSQL DSN | Repaired on active Draft | RED `34010cdb4267afafd7e06246b29cf7765403cae3`; fix `ed081bbe21deb49938d32895c6b6eab267d94cf0` keeps the exact DSN package-internal and removes the public accessor. |
| Canonical RLS policy name could mask policy drift or additional widening policy | Repaired on active Draft | Migration verifies command, permissive mode, PUBLIC role, both stored expressions, rejects unknown policy names, and verifies canonical v2 before retiring known predecessors. Policy predicates bind equality and `current_setting` through `pg_catalog`. Exact-head PostgreSQL execution remains required. |
| Existing-table `CREATE TABLE IF NOT EXISTS` could skip payload grammar/integrity CHECKs | Repaired on active Draft; hosted GREEN pending | PostgreSQL explicitly does not guarantee an existing relation resembles the requested `CREATE TABLE IF NOT EXISTS` definition. RED `5fb675259311f8f9ec9e1f5142ad1992ec1f2915` requires post-create convergence. Fix `221c86571ca5142586d75e75c67f257a127c1189` adds validated inheritable canonical payload CHECK v1; `5d1ddd22034af2ba71eddeea0107113bec78abd4` binds its comment stamp to a reproducible SHA-256 of the reviewed grammar. The real PostgreSQL smoke removes the legacy event-type CHECK and canonical payload CHECK, reapplies migration, verifies catalog state, and requires an invalid mixed-case event type to fail. Package/Docker SQL is byte-identical at `a308bc7bb6c9719142c34e261717c1f3cd2f5564`. Exact-head container execution remains required before GREEN is claimed. |
| Canonical UTC timestamp CHECK name could mask noncanonical state | Repaired on active Draft | Canonical checks require validated inheritable CHECK state plus package semantic stamps; stale same-name constraints are rebuilt once. Exact-head PostgreSQL execution remains required. |
| Existing table could lack the nondeferrable `(tenant_scope, evidence_id)` replay arbiter | Repaired on active Draft | RED `939b5ae55f42c63205e9b86618272fcfecca4791`; migration converges a validated nondeferrable UNIQUE with exact `conkey` order. Runtime `ON CONFLICT (tenant_scope, evidence_id) DO NOTHING` therefore has a schema-level arbiter after successful migration. |
| Same-name operational index could have the wrong key order or unusable catalog state | Repaired on active Draft; hosted GREEN pending | Static RED `e7174cfe11874ef815dc53bd0d48af3cc2cf0d3e`, executable PostgreSQL specimen `338a1ddb753b0fb03d1e8de5643d28a550f32f44`, and tightened fail-closed contract `e5e4db86cd1d5348056c248f3b9600e27120f3e7` prove that name-only `CREATE INDEX IF NOT EXISTS` is insufficient. Causal fix `0c17c6bc8143f941dd13c12d677ffcc933785479` admits only a public, valid/ready/live, nonunique two-key B-tree over exactly `(tenant_scope, created_at)` with no expression or predicate; it repairs a same-target wrong index once and fails closed on an unrelated same-name relation. Exact-head container execution remains required before GREEN is claimed. |
| Exact-head executable evidence for active #319 stack | Waiting on hosted runner | CI and Release Acceptance must execute against the final exact head. Predecessor or superseded-head GREEN is not transferable. |
| Dependency root #233 | Protected merge prerequisite | Re-read exact head, required checks, CodeQL compatibility evidence, independent reviews, and unresolved threads before merge. Do not self-approve or weaken gates. |
| Immutable Context Graph / enterprise architecture / orchestrator authority | Blocked until compatible immutable releases exist | Re-read tag, source commit, artifact digest, provenance, schema/profile, admission, and conformance identities before any production binding. Mutable PR heads remain candidate evidence only. |
| Commercial PostgreSQL driver migration | Separate active writer | PR #323 owns that slice. No overlapping rewrite or destructive restack from this lane. |
| Release package / SBOM / provenance / rollback proof | Not yet releasable | Perform only after the exact protected head is merge-ready and owner gates are terminal green. Version, CHANGELOG, tag, package, immutable release, SBOM, provenance, reproducibility, and rollback evidence must identify the same source. |
| Buyer-path p95 ≤ 20 ms | Unproven for this slice | Do not infer the threshold from unit tests or warm-cache microbenchmarks. Measure applicable PostgreSQL/API paths with realistic/right-cleared data and full connection lifecycle once hosted/runtime execution is available. |

## Integrity decision trace: lifecycle payload CHECK convergence

**Problem.** Migration 0008 originally put tenant scope, event/evidence identity, digest,
and truth-status CHECKs only inside `CREATE TABLE IF NOT EXISTS`. PostgreSQL documents
that `IF NOT EXISTS` suppresses the duplicate-relation error but does not guarantee the
existing relation resembles the requested definition. A restored, manually repaired,
or stale installation could therefore lack one or more payload constraints while the
migration continued successfully. The Python validator does not replace a durable
database invariant because rows can outlive a process and PostgreSQL is the canonical
durability boundary for this outbox.

**Constraints.** Preserve existing rows, package/Docker migration byte parity, one
atomic migration statement, current fresh-install behavior, and idempotent reapply.
Do not rewrite a current canonical CHECK on every run. Do not claim that a comment hash
protects against a privileged operator deliberately forging package metadata.

**Alternatives.** Relying only on Python validation was rejected because it leaves
restored/directly written durable rows outside the database contract. Keeping only the
CREATE-time individual checks was rejected because the exact PostgreSQL
`IF NOT EXISTS` contract makes them non-convergent. Unconditionally dropping and
recreating checks on every migration was rejected because validation rescans existing
rows and takes avoidable table locks.

**Decision.** Migration 0008 now converges one aggregate
`ck_llm_context_lifecycle_outbox_payload_canonical_v1` after table creation. The guard
requires a validated inheritable CHECK with a package-owned comment stamp. The stamp is
not an opaque invented identifier: test code reconstructs the reviewed grammar as a
canonical newline-delimited specification and requires its SHA-256 to equal
`29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a`. A missing or
stale same-name constraint is rebuilt once; PostgreSQL validates existing rows before
the migration succeeds.

The container specimen removes both the legacy event-type check and canonical payload
check, reapplies migration after `CREATE TABLE IF NOT EXISTS` necessarily skips table
creation, verifies the canonical constraint is `CHECK`, validated, inheritable and
stamped, then attempts a mixed-case `event_type` that would have passed after the
legacy check removal. Success is defined by PostgreSQL rejecting that row. A subsequent
migration reapply verifies the canonical state remains idempotent.

**Effect.** Successful migration now re-establishes the durable row-value grammar for
existing outbox tables rather than assuming CREATE-time checks survived. This slice
does not yet claim generic convergence of every column type, default, nullability,
primary-key definition, extension identity, or privileged-operator mutation; those are
separate review surfaces. Hosted exact-head PostgreSQL execution is required before
this repair is called GREEN.

## Reliability/performance decision trace: lifecycle operational-index convergence

**Problem.** Migration 0008 ended with `CREATE INDEX IF NOT EXISTS
idx_llm_context_lifecycle_outbox_tenant_created ON ... (tenant_scope, created_at)`.
PostgreSQL documents that `IF NOT EXISTS` only suppresses the name-collision error;
it does not guarantee that the existing index resembles the requested definition.
A restored, manually repaired, or partially migrated database could therefore retain
that canonical name on `(created_at, tenant_scope)`, a partial/expression index, an
invalid index, a different access method, or another unusable shape. Migration would
succeed while the tenant-first operational access path silently disappeared.

**Constraints.** Preserve the established `(tenant_scope, created_at)` read path,
package/Docker SQL parity, idempotent reapplication, existing data, and the
single-transaction migration. A current index must not be rebuilt on every run.
Migration must not silently drop an unrelated same-name relation.

**Alternatives.** Keeping `CREATE INDEX IF NOT EXISTS` was rejected because name
identity is weaker than index identity. Unconditional drop/recreate was rejected
because it imposes avoidable lock/build cost on every current installation. Silently
dropping any object returned by the canonical name was rejected because that turns a
catalog collision into an unreviewed destructive migration.

**Decision.** Migration 0008 now admits the operational index only when PostgreSQL
catalog state proves all of the following: target relation is the lifecycle outbox;
index namespace is `public`; access method is B-tree; `indisvalid`, `indisready`, and
`indislive` are true; the index is nonunique; there are exactly two key/total
attributes; there is no expression or predicate; and `indkey` resolves exactly to
`tenant_scope` followed by `created_at`. If the canonical name exists as an index on
the target relation but fails that contract, migration drops and recreates it once.
If the canonical name resolves to an unrelated relation, migration raises the fixed
`lifecycle outbox operational index name collision` exception instead of deleting it.

The PostgreSQL container smoke deliberately creates the same canonical name with the
wrong key order, reapplies migration 0008, then checks `pg_index`, `pg_class`, and
`pg_am` for the canonical shape. A second reapplication proves the current state is
idempotent. Static tests pin the same catalog contract so later refactors cannot
return to name-only admission.

**Effect.** A successful migration establishes the tenant-first operational index
shape rather than merely its name. This removes one avoidable source of production
latency drift and makes restore/migration convergence observable. It does not claim
the buyer-path p95 target is met; that remains a separate realistic-data performance
acceptance gate. Hosted exact-head PostgreSQL execution is required before this repair
is called GREEN.

## Release gate

A release is incomplete while any runnable merge, fix, test, restack, review/thread,
owner-path, documentation-to-code, or buyer-gap action remains. Before release,
perform two fresh live sweeps and require the exact protected head, required checks,
review state, security evidence, immutable dependency identities, and release
artifacts to agree. Routine status reporting is not completion evidence.

## References

PostgreSQL Global Development Group. (2026a). *Schemas*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/ddl-schemas.html

PostgreSQL Global Development Group. (2026b). *pg_policy*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026c). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html

PostgreSQL Global Development Group. (2026d). *CREATE POLICY*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026e). *pg_constraint*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-constraint.html

PostgreSQL Global Development Group. (2026f). *INSERT*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-insert.html

PostgreSQL Global Development Group. (2026g). *CREATE TABLE*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-createtable.html

PostgreSQL Global Development Group. (2026h). *CREATE INDEX*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-createindex.html

PostgreSQL Global Development Group. (2026i). *pg_index*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-index.html

PostgreSQL Global Development Group. (2026j). *ALTER TABLE*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-altertable.html
