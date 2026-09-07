# Product–technical gap baseline

## Product responsibility

`ContextualWisdomLab/pg-llm-batch` is the canonical PostgreSQL foundation for durable/asynchronous LLM batch execution, token/size accounting, lifecycle persistence, tenant/RLS enforcement, result streaming/application, and the provider-neutral `BatchInferencePort` boundary. Host products retain authentication journeys, tenant selection, buyer workflow, and domain truth; consumers use released contracts rather than copied source, cross-service SQL, or mutable sibling heads.

## Bounded-context map

- **Provider Batch Gateway:** provider-neutral batch inference and provider HTTP/file adapters. External provider identifiers remain adapter contracts rather than internal domain authority.
- **Durable Batch Lifecycle:** tenant-scoped lifecycle persistence with business identity `(tenant_scope, endpoint_alias, remote_batch_id)`, forced PostgreSQL RLS, and durable transition evidence.
- **Result Streaming:** bounded provider JSONL decoding and resumable `BatchResultCheckpoint` evidence.
- **Result Application:** applies one `CheckpointedBatchResultRecord` effect and advances its checkpoint in the same caller-owned transaction. Package-owned vocabulary is `transaction_cursor`, `checkpointed_record`, `record_effect`, `record_applied`, and `result_checkpoint`; historical public Python names remain compatibility adapters.
- **Recovery / Release Evidence:** descriptor-bound backup/restore and reproducible release evidence without transferring provider or database content into diagnostics.

## DDD vocabulary and invariants

**Aggregates / entities:** durable remote batch lifecycle row and checkpoint consumer state. **Value objects:** `BatchResultCheckpoint`, `CheckpointedBatchResultRecord`, result-application outcome, tenant/provider identities, and bounded accounting values. **Domain services:** provider batch gateway, checkpoint store, result application, lifecycle transition service, and backup/restore verification. **Domain evidence:** lifecycle observations, checkpoint advancement, and content-free recovery/release evidence.

Current invariants include tenant context before persistence/provider work; forced RLS for ordinary application roles; exact checkpoint monotonicity; same-transaction local effect plus checkpoint advance; bounded exact-JSON snapshots; fail-closed malformed or behavior-bearing authority; redacted diagnostics; and no arbitrary SQL or provider payload field becoming authorization/domain authority without validation and translation.

## Result Application source authority

The canonical source/test parent is PR #277 on `fix/result-application-snapshot-b84f0c9`, exact `4937426e3bab44cb62d641de6205bd6da2d934fc`, based on dependency-root #233 exact `01d231fde23b82e2ced258d7bfcb4721ed75706d`.

Hosted predecessor `ea1caf38caf0318e3f2613ab1d208e0236f93194` exposed a real verification defect after its non-force #233 merge: Release Acceptance succeeded and Python 3.10/3.12/3.14 plus PostgreSQL/container jobs passed, but CI `34105321157` failed the repository 100% coverage gate because four integer-budget defensive branches in `result_application.py` were uncovered. Test-only repair `4937426e3bab44cb62d641de6205bd6da2d934fc` covers exhausted byte budget, zero magnitude, negative-sign accounting, and conservative pre-materialization rejection without changing production behavior or public API.

Exact repaired parent evidence is GREEN: Release Acceptance `34107680525` and CI `34107680536` succeeded; coverage/package job `101696358568` recorded `1371 passed / 5 deselected`, production statements `3777/3777`, branches `1066/1066`, `result_application.py` `282/282` statements and `122/122` branches, 100% public docstrings, Ruff/lock/package success, and the Python 3.10/3.12/3.14 plus PostgreSQL/container jobs all succeeded.

## Documentation authority and convergence

PR #324 on `fix/result-application-semantic-identifiers` is the documentation-only child of #277. It owns the Result Application naming explanation in `ARCHITECTURE.md`, `CHANGELOG.md`, `docs/doctoring/result-application-semantic-identifiers.md`, and this baseline; it must not regain production/test authority already owned by #277.

The previous documentation head inherited #277's uncovered-branch failure. It has been non-force restacked onto repaired #277 rather than rebased destructively or allowed to carry stale GREEN. Every documentation edit, including this baseline repair, requires new exact-head verification.

The active lifecycle/outbox security work in sibling PR #319 is not part of this branch ancestry. Therefore this document does not copy #319 source authority or claim its hosted evidence as current-branch truth. Final documentation convergence must occur only after the source topology legitimately integrates the relevant lifecycle/outbox delta; at that point the canonical baseline must preserve both Result Application and lifecycle/outbox evidence rather than selecting one lineage and dropping the other.

## Current product / technical gaps

1. **Dependency-root integration:** #233 remains outside protected `main`. Its normal merge requires all then-live required workflows and a qualifying independent approval; failed or missing central verdict publication cannot be replaced by a synthetic leaf status, self-approval, or routine bypass.
2. **Lifecycle/outbox convergence:** #319 remains a separate security source lineage. Its authority and this Result Application lineage require non-destructive convergence before a single integrated release claim can be made.
3. **Buyer latency envelope:** issue #307 remains an acquisition gap. The applicable package-owned buyer path must measure p50/p95/p99 across connection acquisition, live authority admission, tenant binding, data I/O, cleanup, realistic cardinality/fanout, lock/I/O/connection pressure, saturation, and failure. `p95 <= 20 ms` is an acceptance target, not a current product claim; security/admission work may not be excluded merely to meet it.
4. **Immutable release:** exact-head CI and reproducible build checks are necessary but are not an immutable release. Version/CHANGELOG/tag/package, SBOM, provenance, reproducibility, rollback evidence, and an actual protected-head release remain required before downstream consumers treat this work as released authority.
5. **Consumer integration:** `contextual-orchestrator` and other CWL hosts must consume released package/API/schema contracts and provide authenticated tenant context. Mutable branch dependencies, copied package source, and cross-service SQL remain prohibited.

## Security / operability baseline

The architecture requires bounded provider response processing, exact tenant validation, parameterized transaction-local tenant context, forced RLS, non-superuser/non-`BYPASSRLS` application roles, controlled retries only where semantics permit, bounded snapshots and diagnostics, deterministic checkpoint conflict behavior, explicit connection cleanup, and descriptor-bound recovery/release evidence. Changes to these boundaries require dedicated RED/GREEN regressions and doctoring rather than being hidden inside naming or documentation refactors.

## Evidence status

Protected `main` and every open stack head remain separately authoritative. This baseline records the branch-local Result Application truth and explicitly marks unintegrated sibling/security, performance, approval, and release work as gaps. It does not transfer predecessor checks, claim an unmerged sibling's runtime guarantees, or treat a green development head as a published release.
