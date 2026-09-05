# Product / Technical Gap Baseline

This file records the commercial-development gaps that are owned by
`pg-llm-batch` or materially gate its release. It is evidence, not a substitute
for live PR/check/release reads. The code snapshot assessed here is
`28f44d89a21af76798d7c1dcef7a5bc2cbb31f64`; later documentation-only commits
on the same non-force stack do not change the assessed runtime behavior.

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
| Lifecycle-outbox RLS policy could depend on migration-session name resolution | Repaired on active Draft | RED `6c22770e752dc24666477429835862fd2e43a523`; migration now installs versioned canonical v2 with `OPERATOR(pg_catalog.=)` and `pg_catalog.current_setting`, then retires unqualified v1/legacy policy names. Package/Docker SQL bytes are mirrored. Exact-head hosted execution remains required. |
| Exact-head executable evidence for active Context Fabric consumer-readiness stack | Waiting on runner capacity | PR #319 remains Draft and based on #233. CI and Release Acceptance must execute against the final exact head; predecessor runs are not transferable. |
| Dependency root #233 | Blocked by central evidence/review | Repository-local CI, release acceptance, Security Scan, and Semgrep are green on #233, but the required CodeQL compatibility path lacks authenticated terminal `codeql-dispatch/<language>` evidence and there is no qualifying independent approval. Do not self-approve or bypass. |
| Immutable Context Graph / EA / orchestrator authority | Blocked upstream | No production Context Assertion publication is admitted until compatible immutable releases exist. Re-read tag, version, source commit, artifact digest, provenance, schema/profile, admission, and conformance identities before binding. |
| Commercial PostgreSQL driver migration | Separate active writer | PR #323 owns the driver-neutral migration slice. This writer does not overwrite or restack that sibling lane while it is active. |
| Release package / SBOM / provenance / rollback proof | Not yet releasable | Perform only after protected exact head is merge-ready and all owner gates are terminal green; version, CHANGELOG, tag, package, immutable release, SBOM, provenance, reproducibility, and rollback evidence must refer to the same source identity. |
| Buyer-path p95 ≤ 20 ms | Unproven for this slice | Do not claim the threshold from unit tests or warm-cache microbenchmarks. Measure applicable PostgreSQL/API buyer paths with realistic data and connection lifecycle once this stack can execute on hosted/runtime infrastructure. |

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

PostgreSQL Global Development Group. (2026a). *pg_policy*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026b). *CREATE POLICY*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html
