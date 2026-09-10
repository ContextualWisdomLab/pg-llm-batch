# Requirements Traceability

## Purpose and authority

This map ties canonical PRD/TRD requirements to durable protected-main implementation, tests, ADRs, and operator evidence. It intentionally avoids workflow-run IDs, exact commit SHAs, generated merge commits, and transient review/check state. Rows marked **ACTIVE-PR** or **PARTIAL** are not shipped implementation claims.

## Product-to-technical traceability

| Requirement | Status | Primary protected-main implementation authority | Durable verification/documentation authority | Known gap or active overlay |
| --- | --- | --- | --- | --- |
| FR-1 deterministic bounded batch preparation | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/orchestrator.py`, `pg_llm_batch/token_counter.py`, package schema | preparation/token tests; `docs/idempotent-preparation.md`; `docs/schema-integrity.md` | No gap claimed by the canonical product contract. |
| FR-2 validated bounded provider interaction | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/batch_api_client.py` | provider URL/resource/retry/response-budget tests; `docs/batch-endpoints.md`; `docs/resource-identifiers.md`; ADR 0015 | Provider-specific widening requires a separately reviewed contract. |
| FR-3 standalone + tenant-qualified durable lifecycle | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/durable_client.py`, `pg_llm_batch/db.py`, schema/RLS objects | tenant lifecycle/integration tests; `ARCHITECTURE.md`; `docs/remote-batch-lifecycle.md`; ADR 0002 | Arbitrary SQL, superuser, and BYPASSRLS remain outside the isolation guarantee. |
| FR-4 scheduler-independent bounded reconciliation | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/reconciliation.py` | reconciliation tests and protected-main release gates | Durable candidate discovery remains ACTIVE-PR; autonomous worker semantics remain PARTIAL. |
| FR-4 durable reconciliation candidate discovery | ACTIVE-PR | existing lifecycle/read primitives only | active discovery branch evidence | Candidate selection must remain tenant-qualified, bounded, deterministic, and database-authoritative before integration. |
| FR-4 tenant-qualified cross-process single-flight | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/reconciliation_single_flight.py` | focused single-flight exact-type/traceback tests; merged #191 is historical integration evidence | Protected behavior is a transient PostgreSQL session advisory lock only. It is not a scheduler, durable lease, result-application transaction, terminal-work-retirement mechanism, or distributed exactly-once guarantee. |
| FR-4 durable result application + checkpoint coupling | PARTIAL | `pg_llm_batch/result_streaming.py`, `pg_llm_batch/checkpoint_store.py` provide streaming/checkpoint primitives | ADR 0006; ADR 0007; checkpoint/result-streaming tests; `docs/result-streaming.md` | #194 remains ACTIVE-PR same-transaction local work; protected main still does not claim end-to-end or distributed exactly-once application. |
| FR-5 package persistence integrity | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/db.py`, `pg_llm_batch/schema.sql`, Docker schema mirror | schema-integrity, payload, lifecycle, checkpoint migration tests | Existing-volume legacy-extension retirement remains separately active. |
| FR-5 bounded PostgreSQL recovery evidence primitives | IMPLEMENTED-ON-PROTECTED-MAIN | `postgres_recovery_receipt.py`, `postgres_backup_evidence.py`, `postgres_schema_evidence.py` | focused receipt/artifact/schema evidence tests; merged #205/#206/#207 are historical integration evidence | Evidence identifies bounded bytes/metadata; it does not prove backup execution, restorability, live-schema parity, target isolation, PITR, or RPO/RTO/HA/DR. |
| FR-5 executable PostgreSQL logical backup | ACTIVE-PR | no protected-main `pg_dump` executor | #208 branch evidence only | A backup candidate exists but protected main must not be described as creating a restorable backup. |
| FR-5 executable PostgreSQL logical restore | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/postgres_logical_restore.py` | logical-restore tests and integrated restore-seek ADR/docs; merged #212 is historical integration evidence; closed #209 is predecessor defect evidence | The bounded direct executor accepts custom-format random-access seek behavior and verifies archive metadata instead of final EOF. It does not provide `pg_dump`, authenticated target isolation, post-restore catalog/application readiness, PITR, or RPO/RTO/HA/DR. |
| FR-5 recovery evidence binding and live re-verification | ACTIVE-PR | protected main exposes the underlying receipt/schema/artifact evidence primitives only | active binding/reinspection branch evidence | Bind-time composition and later re-inspection are not provenance, restore proof, or target isolation. |
| FR-5 post-restore catalog/application acceptance | ACTIVE-PR | protected schema/recovery/restore primitives only | active catalog work plus #296 application-readiness candidate | Same-name decoys, key order, constraints, language/function identity, current-role privileges, and live PostgreSQL behavior must fail closed before this can become shipped acceptance. |
| FR-5 permanent live PostgreSQL integration acceptance | ACTIVE-PR | protected main has existing CI but not the #341 permanent integration lane | #341 branch executes `pytest -m integration`; #296 is its active child | Branch-level GREEN does not make the workflow or #296 specimen protected-main truth. |
| FR-5 physical/WAL/PITR recovery | ACTIVE-PR / PARTIAL | bounded protected evidence only | active physical/WAL/PITR branch tests and ADR evidence | Intent/evidence does not prove `pg_basebackup`, WAL archive/replay, promotion, or achieved recovery objectives. |
| FR-5 restore-target isolation | PARTIAL | no authenticated target-isolation proof exists on protected main | current recovery acceptance requirements | Distinct service/configuration labels are not proof that two names resolve to different clusters. |
| FR-5 end-to-end PostgreSQL recovery readiness | PARTIAL | bounded evidence primitives plus bounded logical restore executor | issue-level recovery acceptance plus protected recovery tests | No protected isolated restore drill yet proves schema/RLS/constraint/extension parity, migration compatibility, external key/config custody, physical/WAL/PITR recovery, or measured RPO/RTO/HA/DR. |
| FR-5 legacy `http` / `pg_cron` retirement on existing volumes | ACTIVE-PR | protected main does not yet contain the complete retirement migration contract | active migration/smoke/operator evidence | Keep separate from already-shipped tenant lifecycle migration. |
| FR-6 PostgreSQL-backed configuration/secrets | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/config.py`, schema | config/secret/bootstrap tests | Protected main supports optional Fernet and explicit compatibility mode. `SecretStore(require_encryption=False)` can persist `is_encrypted = FALSE`; this is not a mandatory encryption-at-rest claim. |
| FR-6 production secret-at-rest policy lifecycle | PARTIAL | callers can opt into `require_encryption=True` with usable Fernet configuration | config/secret/bootstrap tests; #210 active stricter runtime/operator-contract work | Historical compatibility-row migration, key rotation/recovery, external custody, and a mandatory default are not protected guarantees. |
| FR-7 bounded diagnostics/readiness | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/health.py`, bounded error surfaces | health/confidentiality tests and architecture requirements | Broader generic rejected-value confidentiality remains active work. |
| FR-7 generic validation rejected-value confidentiality | ACTIVE-PR | protected `ValidationError` compatibility baseline | active privacy/compatibility branch evidence | Intended safe-default redaction remains unshipped until exact source/governance evidence integrates. |
| FR-7 opt-in OpenTelemetry | IMPLEMENTED-ON-PROTECTED-MAIN / packaging PARTIAL | `pg_llm_batch/observability.py` | observability tests | First-class locked installation extra remains ACTIVE-PR. |
| FR-8 standalone + modular MSA deployment | IMPLEMENTED-ON-PROTECTED-MAIN | package/CLI/container composition; injectable host seams | `README.md`, `ARCHITECTURE.md`, package/container tests | CWL host repositories are optional integrations, not package runtime dependencies. |
| Exact owned 100% statement/branch coverage | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | repository CI configuration and owned production code | coverage gate/tests | Must be re-proven on every changed exact head; predecessor evidence never transfers. |
| Python 3.10/3.12/3.14 validation | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | package metadata/workflow matrix | exact-head repository CI | Queued/skipped/infrastructure-failed jobs are not proof. |
| Reproducible release evidence | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/release_evidence.py` and release workflows | ADR 0003; ADR 0004; release-evidence/artifact-identity tests | Publication itself occurs only from a fully accepted integrated protected head. |
| SBOM/provenance/artifact identity | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | release workflows/evidence helpers | release acceptance and artifact verification tests | Repository evidence does not imply external certification. |
| SOC 2 / CSAP evidence readiness | PARTIAL | security, tenancy, logging, release and governance controls | PRD/TRD/security tests/ADRs | Evidence readiness only; no certification is claimed. |

## Security and privacy traceability

| Control objective | Protected-main authority | Verification evidence | Residual boundary |
| --- | --- | --- | --- |
| Trusted tenant selection | `AGENTS.md`, `ARCHITECTURE.md`, tenant validation in DB/durable-client paths | tenant-scope/RLS tests | Host authentication/authorization remains external. |
| RLS defense in depth | tenant-qualified schema and transaction-local scope binding | live PostgreSQL isolation/migration tests | Superuser/BYPASSRLS/arbitrary SQL are administrative bypasses. |
| Provider destination validation | `batch_api_client.py` | endpoint/URL tests | Host/network infrastructure TLS policy is external. |
| Bounded provider input | provider client + result streaming | response/download/JSONL/resource-budget tests | Provider authenticity is not established by payload validation. |
| Reconciliation exclusion | `reconciliation_single_flight.py` | exact-type, lock/release and traceback regressions | Session lifetime is not a durable lease; scheduler and terminal retirement remain separate. |
| Secret/config boundary | `config.py`, bootstrap contract | config/secret/bootstrap tests | Optional Fernet plus compatibility mode are protected behavior; mandatory encryption, compatibility-row migration, rotation/recovery, and external key custody are not. |
| Diagnostic confidentiality | health/error/logging contracts | traceback/health/redaction tests | Generic rejected-value confidentiality remains incomplete on protected main. |
| Checkpoint concurrency/integrity | `checkpoint_store.py` | CAS/concurrency/RLS/rollback tests | PostgreSQL atomicity does not extend to external systems. |
| Recovery evidence confidentiality/integrity | recovery receipt/artifact/schema modules | focused recovery evidence regressions | Evidence does not authenticate an operator, prove target isolation, or prove restore semantics. |
| Logical restore execution | `postgres_logical_restore.py` | custom-format seek, metadata, environment and transactional regressions | Command execution does not prove target identity, application readiness, PITR, or achieved RPO/RTO. |
| Release artifact integrity | `release_evidence.py` + release contracts | descriptor/dirfd/reproducibility tests | Publication credentials and external registry availability remain operational dependencies. |

## Data and persistence traceability

| Data family | Durable identity / authority | Principal protected-main documents | Recovery / non-guarantee |
| --- | --- | --- | --- |
| Tenant lifecycle state | `(tenant_scope, endpoint_alias, remote_batch_id)` | `ARCHITECTURE.md`, ADR 0002, `docs/remote-batch-lifecycle.md` | Tenant scope must come from trusted host authorization; direct SQL bypass is out of scope. |
| Result checkpoints | `(tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id)` | ADR 0006, ADR 0007, `docs/result-streaming.md` | Prefix checkpoint is not provider authentication or whole-stream immutability; cross-system exactly-once is not claimed. |
| Package JSONL/payload state | package-owned schema identities and virtual payload references | PRD/TRD, schema-integrity and payload docs/tests | Persisted package data is canonical, not a disposable cache. |
| Configuration/secrets | `com_config`, `com_secrets` | PRD/TRD and config tests | Compatibility mode can persist `is_encrypted = FALSE`; optional Fernet support is not a mandatory policy. Migration, key rotation/recovery, and external custody remain separate. |
| PostgreSQL recovery evidence | bounded receipt metadata plus backup/schema SHA-256 and byte-size evidence | protected recovery evidence modules/tests; canonical PRD/TRD | Evidence does not persist a backup, execute backup, prove isolated target parity, or establish PITR/RPO/RTO/HA/DR. |
| Release evidence | descriptor/artifact identity contracts | ADR 0003, ADR 0004 | Evidence proves reviewed artifact identity, not organizational certification. |

## Active overlay register

The following open pull requests are represented only as overlays. Their existence does not make their behavior protected-main truth, and this register intentionally avoids volatile Draft/Ready/check-state labels:

- **#175** — OpenTelemetry packaging extra; dependency-lock/materialization and final package evidence remain outside protected-main truth.
- **#184** — existing-volume legacy PostgreSQL extension retirement; migration/operator behavior remains active until merged.
- **#190** — durable reconciliation candidate discovery; not protected-main truth.
- **#194** — atomic local result-effect/checkpoint application; same-transaction behavior remains active and is not end-to-end exactly-once proof.
- **#202** — compatibility-aware rejected-value confidentiality hardening; current candidate evidence does not transfer into shipped behavior.
- **#208** — bounded logical PostgreSQL backup executor using `pg_dump`; active source only and not evidence that protected main can create a restorable backup.
- **#210** — configuration/secrets runtime/operator contract successor; least-privilege readiness and stricter policy work remain unshipped until normal integration.
- **#215** — recovery receipt evidence-binding candidate; object composition must not be mistaken for inspection provenance.
- **#219** — physical/WAL/PITR recovery-profile candidate; records caller-owned intent/objectives but does not prove recovery execution.
- **#221** — recovery-receipt live re-inspection candidate; integrity agreement remains time-bound and does not prove restore success or target isolation.
- **#222** — read-only workflow-registry audit candidate; governance tooling remains an overlay until normal integration.
- **#223** — live PostgreSQL restore-catalog acceptance candidate; catalog/index semantics remain unshipped.
- **#229** — current canonical documentation landing vehicle. It repairs stale capability classification without taking ownership of root `ARCHITECTURE.md`, `CHANGELOG.md`, or product-gap-baseline paths.
- **#296** — isolated restore application-readiness candidate; branch evidence proves bounded catalog/language/privilege checks but not end-to-end recovery readiness.
- **#341** — permanent live PostgreSQL integration-lane candidate; current branch evidence executes the full integration marker and carries #296 as a tested child, but the workflow is not protected-main authority until normal integration.

Merged #191 and #212 are protected-main history, not active overlays. Closed documentation predecessors #214 and #226 are superseded historical lineage; they explain why this overlay avoids transient PR-state instructions but are not current authority. Closed recovery predecessors including #209 remain historical defect evidence only where they explain a current safety invariant.

This register is descriptive, not a substitute for refetching GitHub. Before changing a status, verify the PR still exists, its current contributor head, live protected-main ancestry, reviews/threads, exact-head gates, and resulting protected integration.

## Change-control rule

When a capability merges, update the PRD/TRD status and this traceability map only after reading the new protected-main tree. When a capability is abandoned or superseded, retain historical context only where it explains a live constraint. New requirements must identify an intended implementation authority and deterministic verification authority before they can be called acquisition-ready.
