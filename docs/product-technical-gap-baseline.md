# Product / Technical Gap Baseline

This file records the commercial-development gaps that are owned by
`pg-llm-batch` or materially gate its release. It is evidence, not a substitute
for live PR/check/release reads. The runtime code snapshot assessed here is
`c77ad8895634d96a5da86288e48cb843241f1a6f`; the row-lock authority RED is
`c6c03c4667d0d4f61f6fade694d84e87c6c4e0b4`. The migration DDL target repair is
`6d0b1b5359355fae8b45ceb3162ff7165150f766` with byte-identical Docker mirror
`99218d034c0763bfa496e16fbae790fc7e099982`. Later documentation-only commits on
the same non-force stack do not change the assessed runtime behavior.

## Canonical product boundary

`pg-llm-batch` owns PostgreSQL-backed durable/asynchronous LLM batch
preparation, token/size accounting, provider-neutral batch lifecycle ports,
tenant/RLS persistence, recovery evidence, and result ingestion. Model/provider
discovery, routing, fallback, and credentials remain outside this bounded
context. Context Fabric integration may consume only immutable released
contracts through a pg-owned anti-corruption layer; mutable sibling branches or
cross-service SQL are not production authority.

## Current gaps and disposition

| Gap | State | Current evidence / required next condition |
| --- | --- | --- |
| Lifecycle-outbox runtime/migration object resolution inherited caller `search_path` | Repaired on active Draft | Initial RED `fdf1be5b02f2bf1cc7fbddfb3e908a2d232303cf` exposed ambient name-resolution authority. First runtime fix `21866e42d54a924b6970daf3640d99583eff50d0` removed ambient lookup but changed the caller-owned transaction's `search_path`; follow-up RED `941d0cae253722ec8c5c82c5d86e9b5962707712` rejects that composition side effect. Final runtime fix `2b5a7eb1b7e5c2f19628290e6e50fb57d31d6549` uses `pg_catalog.set_config` for the tenant GUC and `public.llm_context_lifecycle_outbox` for reads/writes without mutating caller `search_path`; fake/test alignment is `f3fb547f3924aaf49c7cd8b40f978d4618c8e119`. Installer RED `757c08afe51694208425677e6a2cf92d20dd9f15` then caught that `pg_catalog` first in `search_path` also makes an unqualified `CREATE TABLE` target the wrong current schema. Package migration `6d0b1b5359355fae8b45ceb3162ff7165150f766` explicitly creates `public.llm_context_lifecycle_outbox`; Docker mirror `99218d034c0763bfa496e16fbae790fc7e099982` has the same blob. Rollback `63aba47bcbf9cc71467cd2ad598a0708a9994bf0` retains its installer-owned reviewed path. Exact-head hosted execution remains required. |
| Lifecycle-outbox caller-controlled row-lock mode accepted arbitrary truthy objects | Repaired on active Draft | RED `c6c03c4667d0d4f61f6fade694d84e87c6c4e0b4` adds a public transaction-boundary regression requiring `for_update` to be an exact built-in boolean before truthiness or SQL; behavior-bearing `__bool__`, integer, string, and null authorities are rejected without database interaction. Causal source fix `c77ad8895634d96a5da86288e48cb843241f1a6f` validates the lock decision before tenant GUC binding or relation access and preserves exact `False`/`True` semantics. Exact-head hosted execution remains required. |
| Lifecycle-outbox store publicly exposed its admitted PostgreSQL DSN | Repaired on active Draft | RED test commit `34010cdb4267afafd7e06246b29cf7765403cae3` requires that an admitted store have no public `postgres_dsn` accessor and that a credential-bearing DSN not appear in its representation. Causal source fix `ed081bbe21deb49938d32895c6b6eab267d94cf0` keeps the exact DSN only in the package-owned weak binding and uses it internally for connections. Exact-head hosted execution remains required. |
| Lifecycle-outbox RLS policy could depend on migration-session name resolution | Repaired on active Draft | RED `6c22770e752dc24666477429835862fd2e43a523`; migration now installs versioned canonical v2 with `OPERATOR(pg_catalog.=)` and `pg_catalog.current_setting`, then retires unqualified v1/legacy policy names. Package/Docker SQL bytes are mirrored. Exact-head hosted execution remains required. |
| Exact-head executable evidence for active Context Fabric consumer-readiness stack | Waiting on runner capacity | PR #319 remains Draft and based on #233. CI and Release Acceptance must execute against the final exact head; predecessor runs are not transferable. |
| Dependency root #233 | Blocked by central evidence/review | Repository-local CI, release acceptance, Security Scan, and Semgrep are green on #233, but the required CodeQL compatibility path lacks authenticated terminal `codeql-dispatch/<language>` evidence and there is no qualifying independent approval. Do not self-approve or bypass. |
| Immutable Context Graph / EA / orchestrator authority | Blocked upstream | No production Context Assertion publication is admitted until compatible immutable releases exist. Re-read tag, version, source commit, artifact digest, provenance, schema/profile, admission, and conformance identities before binding. |
| Commercial PostgreSQL driver migration | Separate active writer | PR #323 owns the driver-neutral migration slice, including `pg_llm_batch/db.py`. This writer does not overwrite or restack that sibling lane while it is active. |
| Release package / SBOM / provenance / rollback proof | Not yet releasable | Perform only after protected exact head is merge-ready and all owner gates are terminal green; version, CHANGELOG, tag, package, immutable release, SBOM, provenance, reproducibility, and rollback evidence must refer to the same source identity. |
| Buyer-path p95 ≤ 20 ms | Unproven for this slice | Do not claim the threshold from unit tests or warm-cache microbenchmarks. Measure applicable PostgreSQL/API buyer paths with realistic data and connection lifecycle once this stack can execute on hosted/runtime infrastructure. |

## Security decision trace: lifecycle-outbox database name authority

**Problem.** The outbox policy predicate already bound its security-sensitive
operator/function names to `pg_catalog`, but runtime relation access and migration
0008 still inherited PostgreSQL `search_path`. PostgreSQL resolves unqualified
relation, type, function, and operator names through that path; temporary schemas
also receive special lookup treatment unless explicitly placed. A caller-controlled
or misconfigured session path could therefore select a same-named object before the
reviewed outbox relation or influence migration object resolution. Conversely, once
`pg_catalog` is deliberately first, an unqualified `CREATE TABLE` would use the wrong
current schema for creation rather than the intended `public` application schema.

**Constraints.** The repair must preserve the package's existing `public` application
schema, forced RLS, transaction-local tenant binding, caller-owned transaction seam,
package/Docker migration parity, and atomic rollback refusal. It must not modify the
shared `db.py` helper because active sibling PR #323 currently owns that file. A
caller-owned transaction's pre-existing `search_path` is also caller state; the
outbox must not silently rewrite it merely to protect its own object resolution.

**Alternatives.** Leaving ambient `search_path` unchanged while retaining unqualified
runtime names was rejected because it leaves object authority to the caller session.
The first causal attempt, `SET LOCAL search_path = pg_catalog, public, pg_temp`, was
rejected for the runtime seam after follow-up review because `SET LOCAL` persists for
the remainder of the caller's transaction and can change unrelated domain SQL.
Changing the shared tenant helper was rejected because #323 currently owns `db.py`.
Fully qualifying the runtime tenant-setting function and outbox relation is smaller
and preserves caller state. Migration and rollback are different: each owns its
single atomic installer/destructive statement, so transaction-local path binding
there does not leak into caller domain work. Putting `public` first for migration was
rejected because it would restore a writable-schema-before-catalog lookup hazard; the
creation target is instead qualified explicitly.

**Decision.** Runtime uses fully qualified
`pg_catalog.set_config('pg_llm_batch.tenant_scope', ..., true)` and addresses the
canonical relation as `public.llm_context_lifecycle_outbox`; it does not issue
`SET LOCAL search_path`. Forward migration and destructive rollback `DO` blocks use
fully qualified `pg_catalog.set_config` to bind `pg_catalog, public, pg_temp` before
object lookup or DDL. Migration creation is explicitly
`CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox`, so secure lookup
order cannot redirect the DDL target. Explicitly placing `pg_temp` last prevents its
implicit precedence in installer-owned statements.

**Effect.** Ambient session `search_path` is no longer authority for supported
outbox runtime, installation, or rollback object resolution; creation is fixed to the
canonical application schema; and the runtime seam leaves the caller transaction's
name-resolution state unchanged. This does not claim that an untrusted principal with
`CREATE` authority in canonical `public` is safe; schema ACLs remain an operator trust
boundary. Exact-head PostgreSQL execution is still required before the repair is
hosted GREEN evidence.

## Security decision trace: lifecycle-outbox row-lock authority

**Problem.** `load_in_transaction(..., for_update=...)` used the caller value directly
in a Python truthiness decision. Although the public type annotation says `bool`,
runtime callers could pass an integer, string, null, or an object with caller-defined
`__bool__`. A truthy non-boolean could silently request `FOR UPDATE`; a behavior-bearing
object could execute caller code before the database boundary. The lock decision is
transaction authority and must not be inferred from Python coercion.

**Constraints.** Preserve the existing public parameter and the two legitimate modes:
exact `False` performs a tenant-qualified unlocked read; exact `True` performs the same
read with `FOR UPDATE`. Invalid authority must fail before transaction-local tenant
binding, relation access, or caller-controlled truthiness. Diagnostics must remain
content-free.

**Alternatives.** `bool(for_update)` was rejected because it explicitly executes the
behavior-bearing coercion being removed. Accepting `0`/`1` for convenience was rejected
because Python integers are not the lock authority contract and silently widen the
public transaction semantics. Removing the public flag was unnecessary because the
compare-and-swap outbox path legitimately uses it.

**Decision.** Require `type(for_update) is bool` at the start of
`load_in_transaction`. Invalid values raise the package `ValidationError` with a fixed
redacted value before any SQL. Only the validated exact boolean controls whether the
query receives `FOR UPDATE`.

**Effect.** Caller-defined truthiness and accidental truthy values cannot acquire a
row lock or execute behavior at the outbox transaction boundary. The repair does not
change tenant scope, isolation level, lock duration, deadlock policy, or the existing
compare-and-swap protocol. Exact-head hosted execution remains required.

## Security decision trace: lifecycle-outbox DSN authority

**Problem.** `PostgresContextLifecycleOutboxStore` retained an exact PostgreSQL
DSN in a package-owned binding but also exposed that value through a public
`postgres_dsn` property. PostgreSQL connection URIs commonly carry user/password
material, so an immutable authority binding should not also become a routine
logging or diagnostic surface.

**Constraints.** The exact admitted database target must remain immutable for
`load()` and `enqueue()`; tenant/RLS bindings and caller-owned transaction seams
must remain unchanged. This is accidental-exposure minimization, not a claim
that hostile in-process Python code cannot inspect module internals.

**Alternatives.** Returning a redacted DSN was rejected because robustly
canonicalizing every libpq DSN form would create a second connection-string
parser and an unnecessary public API. Retaining the exact public property was
rejected because no caller operation requires it.

**Decision.** Keep the exact DSN only in `_OUTBOX_STORE_BINDINGS` and consume it
directly for package-owned connection acquisition. `tenant_scope` and its
content-free SHA-256 identity remain observable because they are authorization
and evidence identities, not connection credentials.

**Effect.** Normal store representation and public attributes no longer expose
a credential-bearing database target. Connection routing remains bound to the
same construction-time DSN. Exact-head unit/coverage execution is still required
before this repair is GREEN evidence.

## Security decision trace: lifecycle RLS policy v2

**Problem.** Migration 0008 previously created a tenant policy whose equality
operator and `current_setting` function were unqualified. A migration session's
name-resolution environment must not choose security-policy operator/function
authority.

**Constraints.** The fix must preserve forced RLS, default-deny behavior,
transactional migration, package/Docker byte parity, and lock-bounded idempotent
reapplication. Rewriting the same policy on every run would regress the latter.

**Alternatives.** Recreating the unversioned policy on every run was rejected
because it needlessly repeats policy DDL. Treating the existing policy name as
sufficient authority was rejected because PostgreSQL records the policy command,
roles, and expression trees separately in `pg_policy`.

**Decision.** Create `plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2`
once, with `OPERATOR(pg_catalog.=)` and `pg_catalog.current_setting` in both
`USING` and `WITH CHECK`; create v2 before dropping the earlier canonical v1 and
legacy policy names. Current v2 is catalog-gated so ordinary reapplication does
not rewrite it.

**Effect.** Fresh and previously-candidate installations converge to an explicit
PostgreSQL catalog authority while retaining the same tenant predicate. This
fix does not turn the custom setting into a credential and does not protect a
role that is allowed arbitrary SQL, `BYPASSRLS`, or superuser authority.

## Release gate

A release is not complete while any runnable merge/fix/test/restack/review,
owner-path, documentation-to-code, or buyer-gap action remains. Before release,
perform two fresh live sweeps and require the exact protected head, required
checks, review state, security evidence, immutable dependency identities, and
release artifacts to agree. Routine status reporting is not a completion gate.

## References

PostgreSQL Global Development Group. (2026a). *Schemas*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/ddl-schemas.html

PostgreSQL Global Development Group. (2026b). *pg_policy*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026c). *CREATE POLICY*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html
