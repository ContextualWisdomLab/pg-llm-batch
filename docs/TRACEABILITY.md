# Requirements Traceability

## Purpose and authority

This map ties canonical PRD/TRD requirements to durable protected-main implementation, tests, ADRs, and operator evidence. It avoids workflow-run IDs, exact SHAs, generated merge commits, and transient review/check state. **ACTIVE-PR** and **PARTIAL** rows are not shipped claims.

## Product-to-technical traceability

| Requirement | Status | Protected-main authority | Durable evidence | Residual boundary / active overlay |
| --- | --- | --- | --- | --- |
| FR-1 bounded batch preparation | IMPLEMENTED-ON-PROTECTED-MAIN | `orchestrator.py`, `token_counter.py`, package schema | preparation/token/schema tests | No additional shipped claim inferred. |
| FR-2 bounded provider interaction | IMPLEMENTED-ON-PROTECTED-MAIN | `batch_api_client.py` | endpoint/resource/retry/response-budget tests; ADR 0015 | Provider-specific widening requires review. |
| FR-3 durable lifecycle and tenancy | IMPLEMENTED-ON-PROTECTED-MAIN | `durable_client.py`, `db.py`, schema/RLS | tenant lifecycle/live PostgreSQL tests; ADR 0002 | Arbitrary SQL, `SUPERUSER`, and `BYPASSRLS` remain outside tenant isolation. |
| FR-4 bounded reconciliation | IMPLEMENTED-ON-PROTECTED-MAIN | `reconciliation.py` | reconciliation tests | Durable candidate discovery remains ACTIVE-PR. |
| FR-4 tenant-qualified cross-process single-flight | IMPLEMENTED-ON-PROTECTED-MAIN | `reconciliation_single_flight.py` | focused exact-type/lock/traceback tests; merged #191 is historical integration evidence | Session advisory lock only: not scheduler, durable lease, result application, terminal retirement, or distributed exactly-once. |
| FR-4 durable result application | PARTIAL | `result_streaming.py`, `checkpoint_store.py` primitives | ADR 0006/0007 and tests | #194 remains active; no end-to-end exactly-once claim. |
| FR-5 persistence integrity | IMPLEMENTED-ON-PROTECTED-MAIN | `db.py`, `schema.sql`, Docker schema mirror | schema/payload/lifecycle/checkpoint tests | Existing-volume legacy-extension retirement remains active. |
| FR-5 bounded recovery evidence | IMPLEMENTED-ON-PROTECTED-MAIN | `postgres_recovery_receipt.py`, `postgres_backup_evidence.py`, `postgres_schema_evidence.py` | focused evidence tests; merged #205/#206/#207 are historical integration evidence | Identity/integrity only; not backup execution, provenance, restorability, live parity, PITR, or RPO/RTO. |
| FR-5 executable PostgreSQL logical backup | ACTIVE-PR | no protected `pg_dump` executor | #208 branch evidence | Protected main must not be described as creating a restorable backup. |
| FR-5 executable PostgreSQL logical restore | IMPLEMENTED-ON-PROTECTED-MAIN | `postgres_logical_restore.py` | logical-restore regressions; ADR 0016; merged #212 historical integration evidence; #209 predecessor defect evidence | Custom-format seek + metadata verification is protected. No backup, target-authentication, application-readiness, PITR, or RPO/RTO guarantee. |
| FR-5 restore-target cluster identity verification | IMPLEMENTED-ON-PROTECTED-MAIN | `postgres_restore_target.py` | focused service-name/system-identifier tests; ADR 0022; merged #228 historical integration evidence | Requires distinct exact service names and caller-owned `pg_control_system().system_identifier` values. It does not open/authenticate connections, accept DSNs, execute restore, or prove catalog/application/PITR/RPO-RTO readiness. |
| FR-5 effective PITR target configuration observation | ACTIVE-PR | no protected recovery-target configuration observer | #299 fixed-query source/tests plus canonical documentation overlay | Exactly eight reviewed recovery-target settings plus `pg_is_in_recovery()` are observed from a caller-owned isolated target. The APIs remain module-scoped; no connection timeout is imposed; no WAL completeness, target attainment, promotion, application readiness, PITR success, or achieved RPO/RTO is proved. |
| FR-5 recovery evidence binding/reinspection | ACTIVE-PR | underlying protected evidence primitives only | active binding/reinspection branches | Composition/reinspection is not provenance or restore proof. |
| FR-5 post-restore catalog/application acceptance | ACTIVE-PR | protected schema/recovery/restore/target primitives only | active catalog work and #296 application-readiness branch | Exact catalog/function/privilege/live behavior must integrate before becoming shipped acceptance. |
| FR-5 permanent live PostgreSQL integration lane | ACTIVE-PR | current protected CI does not yet contain #341 lane | #341 branch executes the complete integration marker; #296 is its tested child | Branch GREEN is not protected-main workflow authority. |
| FR-5 physical/WAL/PITR recovery | ACTIVE-PR / PARTIAL | bounded protected evidence only | active physical/WAL/PITR branch evidence | Does not prove basebackup, WAL replay, promotion, or achieved objectives. |
| FR-5 end-to-end recovery readiness | PARTIAL | evidence primitives + logical restore + target cluster-identity verifier | protected focused tests plus active acceptance work | Still missing integrated backup execution, connection provenance/authorization, application/catalog parity, migration/key custody, physical/WAL/PITR, and measured RPO/RTO/HA/DR. |
| FR-6 PostgreSQL-backed config/secrets | IMPLEMENTED-ON-PROTECTED-MAIN | `config.py`, schema | config/secret/bootstrap tests | Optional Fernet + base64 compatibility are protected; mandatory policy is not. |
| FR-6 production secret-at-rest lifecycle | PARTIAL | opt-in `require_encryption=True` path | config/secret tests; #210 active work | Compatibility-row migration, rotation/recovery, external key custody, and mandatory default remain unshipped. |
| FR-7 bounded diagnostics/readiness | IMPLEMENTED-ON-PROTECTED-MAIN | `health.py`, bounded error surfaces | health/confidentiality tests | Broader rejected-value confidentiality remains active work. |
| FR-7 opt-in telemetry | IMPLEMENTED-ON-PROTECTED-MAIN / packaging PARTIAL | `observability.py` | observability tests | First-class locked installation extra remains ACTIVE-PR. |
| FR-8 standalone + modular embedding | IMPLEMENTED-ON-PROTECTED-MAIN | package/CLI/container seams | package/container/docs tests | CWL hosts are optional integrations. |
| Exact owned production coverage/docstrings | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | repository CI | exact-head coverage/docstring gates | Re-prove on every changed head. |
| Python 3.10/3.12/3.14 | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | package/workflow matrix | exact-head CI | Queued/skipped/infrastructure failure is not proof. |
| Reproducible release + SBOM/provenance | IMPLEMENTED-ON-PROTECTED-MAIN governance contract | release-evidence code/workflows | release acceptance/artifact tests | Publication is authoritative only from an accepted protected head. |
| SOC 2 / CSAP evidence readiness | PARTIAL | tenancy/security/logging/release controls | PRD/TRD/security/ADR evidence | No external certification claim. |

## Security and privacy traceability

| Control objective | Protected-main authority | Verification | Residual boundary |
| --- | --- | --- | --- |
| Trusted tenant selection | tenant validation + host-boundary docs | tenant/RLS tests | Host authentication/authorization remains external. |
| RLS defense in depth | forced RLS + transaction-local scope | live PostgreSQL isolation/migration tests | Administrative SQL identities bypass the guarantee. |
| Provider destination/input bounds | `batch_api_client.py` | URL/resource/response/download tests | Payload validation does not prove provider authenticity. |
| Reconciliation exclusion | `reconciliation_single_flight.py` | lock/release/exact-type/traceback tests | Session lifetime is not durable leasing. |
| Secret/config boundary | `config.py` | config/secret/bootstrap tests | Optional Fernet does not imply mandatory encryption, rotation, or custody. |
| Diagnostic confidentiality | health/error/logging contracts | health/redaction/traceback tests | Broader generic validation hardening remains active. |
| Checkpoint integrity | `checkpoint_store.py` | CAS/concurrency/RLS/rollback tests | PostgreSQL atomicity does not span external systems. |
| Recovery evidence integrity | receipt/artifact/schema modules | focused evidence tests | No operator authentication, target authority, or restorability proof. |
| Logical restore execution | `postgres_logical_restore.py` | seek/metadata/environment/transaction tests | Command success is not application/PITR/RPO-RTO proof. |
| Restore-target cluster separation | `postgres_restore_target.py` | exact service-name/system-identifier tests | Caller supplies identities from already-opened connections; the package does not authenticate connection provenance or authorize restore. |
| Recovery-target configuration observation | no protected-main implementation | #299 fixed-query branch tests and canonical docs | Caller owns connection/timeouts. Module-scoped branch APIs do not prove WAL completeness, exact stop semantics, promotion, application readiness, PITR success, or achieved RPO/RTO. |
| Release artifact integrity | release-evidence contracts | reproducibility/artifact identity | Publication credentials/registry availability remain operational dependencies. |

## Data and persistence traceability

| Data family | Durable identity / authority | Principal docs | Non-guarantee |
| --- | --- | --- | --- |
| Tenant lifecycle | `(tenant_scope, endpoint_alias, remote_batch_id)` | ADR 0002; lifecycle docs | Host must select tenant authority. |
| Result checkpoint | `(tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id)` | ADR 0006/0007 | Prefix evidence is not provider authentication or exactly-once. |
| Package payload state | package schema identities | PRD/TRD/schema docs | Canonical persisted business state, not disposable cache. |
| Configuration/secrets | `com_config`, `com_secrets` | PRD/TRD/config tests | Compatibility mode can persist `is_encrypted = FALSE`; optional Fernet is not mandatory policy. |
| Recovery evidence | bounded receipt/hash/size values | recovery modules/tests | Does not persist backups or establish restore/PITR/RPO-RTO. |
| Restore-target identity evidence | exact service names + caller-owned `system_identifier` values | ADR 0022; target module/tests | Difference proves bounded name/cluster separation only, not connection provenance, authorization, or application readiness. |
| Release evidence | descriptor/artifact identity | ADR 0003/0004 | Does not establish organizational certification. |

## Active overlay register

The following open PRs are overlays only; their existence does not make behavior protected-main truth:

- **#175** — first-class OpenTelemetry packaging extra.
- **#184** — existing-volume legacy PostgreSQL extension retirement.
- **#190** — durable reconciliation candidate discovery.
- **#194** — atomic local result-effect/checkpoint application.
- **#202** — generic rejected-value confidentiality hardening.
- **#208** — bounded logical PostgreSQL backup executor using `pg_dump`.
- **#210** — stricter configuration/secrets runtime/operator contract.
- **#215** — recovery receipt evidence binding.
- **#219** — physical/WAL/PITR recovery profile.
- **#221** — recovery receipt live reinspection.
- **#222** — read-only workflow-registry audit.
- **#223** — live PostgreSQL restore-catalog acceptance.
- **#229** — current canonical documentation landing vehicle; it does not own root `ARCHITECTURE.md`, `CHANGELOG.md`, or the product-gap baseline.
- **#296** — isolated restore application-readiness candidate.
- **#299** — effective recovery-target configuration observation on a caller-owned isolated target; functions remain module-scoped pending explicit public-surface decision.
- **#341** — permanent live PostgreSQL integration-lane candidate.

Merged #191, #212, and #228 are protected-main history rather than active overlays. Closed #225 is superseded restore-target predecessor lineage; closed #209 remains defect evidence for the invalid EOF restore postcondition. Closed documentation predecessors #214 and #226 are superseded historical lineage only.

This register is descriptive, not a substitute for refetching live GitHub state.

## Change-control rule

After a capability merges, change canonical status only after reading the resulting protected tree. After abandonment or supersession, retain predecessor context only where it explains a current constraint. New requirements need an intended implementation authority and deterministic verification authority before they are acquisition-ready.
