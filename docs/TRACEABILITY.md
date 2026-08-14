# Requirements Traceability

## Purpose and authority

This map ties the canonical PRD/TRD requirements to stable protected-main implementation, test, ADR, and operator evidence. It intentionally avoids workflow-run IDs, predecessor SHAs, generated merge commits, and review comments because those are transient verification records rather than durable requirements authority.

The reference protected-main tree is `d0a4b30be1f46536e352443309f3a35533156767`. Rows marked **ACTIVE-PR** or **PARTIAL** are not shipped implementation claims.

## Product-to-technical traceability

| Requirement | Status | Primary protected-main implementation authority | Durable verification/documentation authority | Known gap or active overlay |
| --- | --- | --- | --- | --- |
| FR-1 deterministic bounded batch preparation | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/orchestrator.py`, `pg_llm_batch/token_counter.py`, package schema | preparation/token tests; `docs/idempotent-preparation.md`; `docs/schema-integrity.md` | No gap claimed by the canonical product contract. |
| FR-2 validated bounded provider interaction | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/batch_api_client.py` | provider URL/resource/retry/response-budget tests; `docs/batch-endpoints.md`; `docs/resource-identifiers.md`; ADR 0015 | Provider-specific widening requires a separately reviewed contract. |
| FR-3 standalone + tenant-qualified durable lifecycle | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/durable_client.py`, `pg_llm_batch/db.py`, schema/RLS objects | tenant lifecycle/integration tests; `ARCHITECTURE.md`; `docs/remote-batch-lifecycle.md`; ADR 0002 | Arbitrary SQL, superuser, and BYPASSRLS remain outside the isolation guarantee. |
| FR-4 scheduler-independent bounded reconciliation | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/reconciliation.py` | reconciliation tests and protected-main release gates | Discovery #190 and single-flight #191 remain ACTIVE-PR; autonomous worker semantics remain PARTIAL. |
| FR-4 durable reconciliation candidate discovery | ACTIVE-PR | none on protected main beyond existing lifecycle/read primitives | PR #190 exact-head evidence only | Not shipped; current review/infrastructure gates must not be transferred. |
| FR-4 tenant-qualified cross-process single-flight | ACTIVE-PR | none on protected main beyond existing DB primitives | PR #191 exact-head evidence only | Not shipped; qualifying independent approval remains a live-governance concern. |
| FR-4 durable result application + checkpoint coupling | PARTIAL | `pg_llm_batch/result_streaming.py`, `pg_llm_batch/checkpoint_store.py` provide streaming/checkpoint primitives | ADR 0006; ADR 0007; checkpoint/result-streaming tests; `docs/result-streaming.md` | PR #194 is ACTIVE-PR test-first work that adds a same-transaction local result-effect/checkpoint seam; protected main still does not claim end-to-end or distributed exactly-once application. |
| FR-5 package persistence integrity | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/db.py`, `pg_llm_batch/schema.sql`, Docker schema mirror | schema-integrity, payload, lifecycle, checkpoint migration tests | Existing-volume legacy-extension retirement is separately ACTIVE-PR #184. |
| FR-5 legacy `http` / `pg_cron` authority retirement on existing volumes | ACTIVE-PR | protected main does not yet contain the retirement migration contract | PR #184 migration/smoke/operator evidence only | Must remain active until unchanged exact head satisfies migration/security/release/review gates and merges. |
| FR-6 PostgreSQL-backed configuration/secrets | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/config.py`, schema | config/secret tests and bootstrap docs | Least-privilege separation of runtime store construction from schema provisioning is ACTIVE-PR #193. Its current candidate moves DDL/default seeding to explicit provisioning and adds bounded catalog relation/type/read-capability probes, but none of that is shipped until normal governance integrates it. |
| FR-7 bounded diagnostics/readiness | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/health.py`, bounded error surfaces | health/confidentiality tests and architecture requirements | Broader `ValidationError` value-confidentiality work must not be inferred as solved from readiness alone. |
| FR-7 opt-in OpenTelemetry | IMPLEMENTED-ON-PROTECTED-MAIN / packaging PARTIAL | `pg_llm_batch/observability.py` | observability tests | First-class locked installation extra remains ACTIVE-PR #175. |
| FR-8 standalone + modular MSA deployment | IMPLEMENTED-ON-PROTECTED-MAIN | package/CLI/container composition; injectable host seams | `README.md`, `ARCHITECTURE.md`, package/container tests | CWL host repositories are optional integrations, not package runtime dependencies. |
| Exact owned 100% statement/branch coverage | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | repository CI configuration and owned production code | coverage gate/tests | Must be re-proven on every changed exact head; predecessor evidence never transfers. |
| Python 3.10/3.12/3.14 validation | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | package metadata/workflow matrix | exact-head repository CI | Requires exact-head terminal success; queued/skipped/infrastructure-failed jobs are not proof. |
| Reproducible release evidence | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/release_evidence.py` and release workflows | ADR 0003; ADR 0004; release-evidence/artifact-identity tests | Release publication itself still occurs only from a fully accepted integrated protected head. |
| SBOM/provenance/artifact identity | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | release workflows/evidence helpers | release acceptance and artifact verification tests | No certification claim follows from repository evidence alone. |
| SOC 2 / CSAP evidence readiness | PARTIAL | security, tenancy, logging, release and governance controls | PRD/TRD/security tests/ADRs | Evidence readiness only; no external certification is claimed. |

## Security and privacy traceability

| Control objective | Protected-main authority | Verification evidence | Residual boundary |
| --- | --- | --- | --- |
| Trusted tenant selection | `AGENTS.md`, `ARCHITECTURE.md`, tenant validation in DB/durable-client paths | tenant-scope/RLS tests | Host authentication/authorization remains external. |
| RLS defense in depth | tenant-qualified schema and transaction-local scope binding | live PostgreSQL isolation/migration tests | Superuser/BYPASSRLS/arbitrary SQL are administrative bypasses. |
| Provider destination validation | `batch_api_client.py` | endpoint/URL tests | Host/network infrastructure TLS policy is external. |
| Bounded provider input | provider client + result streaming | response/download/JSONL/resource-budget tests | Provider authenticity is not established by payload validation. |
| Secret/config boundary | `config.py`, bootstrap contract | config/secret/bootstrap tests | External enterprise secret manager choice remains host-owned. |
| Diagnostic confidentiality | health/error/logging contracts | traceback/health/redaction tests | Generic validation value confidentiality remains an explicit separate gap where applicable. |
| Checkpoint concurrency/integrity | `checkpoint_store.py` | CAS/concurrency/RLS/rollback tests | PostgreSQL atomicity does not extend to external systems. |
| Release artifact integrity | `release_evidence.py` + release contracts | descriptor/dirfd/reproducibility tests | Publication credentials and external registry availability are operational dependencies. |

## Data and persistence traceability

| Data family | Durable identity / authority | Principal protected-main documents | Recovery / non-guarantee |
| --- | --- | --- | --- |
| Tenant lifecycle state | `(tenant_scope, endpoint_alias, remote_batch_id)` | `ARCHITECTURE.md`, ADR 0002, `docs/remote-batch-lifecycle.md` | Tenant scope must come from trusted host authorization; direct SQL bypass is out of scope. |
| Result checkpoints | `(tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id)` | ADR 0006, ADR 0007, `docs/result-streaming.md` | Prefix checkpoint is not provider authentication or whole-stream immutability; cross-system exactly-once is not claimed. |
| Package JSONL/payload state | package-owned schema identities and virtual payload references | PRD/TRD, schema-integrity and payload docs/tests | Persisted package data is canonical, not a disposable cache. |
| Configuration/secrets | `com_config`, `com_secrets` | PRD/TRD and config tests | Runtime/provisioning least-privilege separation is not yet shipped. |
| Release evidence | descriptor/artifact identity contracts | ADR 0003, ADR 0004 | Evidence proves the reviewed artifact path, not organizational certification. |

## Active overlay register

The following open pull requests are intentionally represented only as overlays on this traceability map:

- **#175** — OpenTelemetry packaging extra; dependency-lock/materialization and final package evidence remain outside protected-main truth.
- **#184** — existing-volume legacy PostgreSQL extension retirement; migration/operator behavior remains active until merged.
- **#190** — durable reconciliation candidate discovery; not protected-main truth and currently subject to live review/tooling evidence.
- **#191** — tenant-qualified reconciliation single-flight; not protected-main truth until live approval/gates and merge.
- **#192** — this canonical PRD/TRD/fitness/traceability reconstruction itself.
- **#193** — runtime-store/schema-provisioning separation; a current-main least-privilege implementation is under review, but remains an active overlay rather than shipped behavior.
- **#194** — atomic local result-effect/checkpoint application; a current-main-compatible implementation is under review but remains an active overlay and is not shipped.

This register is descriptive, not a substitute for refetching GitHub. Before changing a status, verify the PR still exists, its exact contributor head, live protected-main base, ancestry, current reviews/threads, exact-head gates, and resulting protected-main integration.

## Change-control rule

When a capability merges, update the PRD/TRD status and this traceability map in a canonical documentation change only after the new protected-main tree is read. When a capability is abandoned or superseded, mark the overlay accordingly rather than silently deleting its historical decision context. New requirements must identify at least one intended implementation authority and one deterministic verification authority before they can be called acquisition-ready.
