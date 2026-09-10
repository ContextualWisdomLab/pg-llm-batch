# Documentation Fitness

## Authority and status model

This inventory evaluates the canonical documentation graph against the live protected-default-branch behavior. It deliberately does not freeze an exact protected commit SHA: exact heads belong in PR and review evidence, while durable documentation records capability contracts. Pull-request content remains work-in-progress until normal protected-branch integration.

The canonical status vocabulary is shared with `docs/product/PRD.md` and `docs/product/TRD.md`: **IMPLEMENTED-ON-PROTECTED-MAIN**, **ACTIVE-PR**, **PARTIAL**, **PLANNED**, and **SUPERSEDED**.

A document is fit only when it agrees with protected code/schema/tests, preserves non-guarantees, keeps active-branch evidence out of shipped claims, and tells an operator or reviewer enough to use, verify, recover, or reject the relevant behavior safely.

The tenant lifecycle material reconstructs protected behavior rather than creating a new tenant/RLS contract. `README.md`, `ARCHITECTURE.md`, `docs/remote-batch-lifecycle.md`, ADR 0002, `docs/doctoring/tenant-scoped-lifecycle.md`, and `CHANGELOG.md` remain companion authorities for trusted tenant selection, `NOSUPERUSER NOBYPASSRLS`, transaction-local forced RLS, arbitrary-SQL limits, legacy-to-`standalone` migration, and rollback constraints.

Protected main also contains bounded recovery-evidence primitives integrated through #205, #206, and #207, the tenant-qualified session advisory single-flight seam integrated through #191, and the bounded direct custom-format logical restore executor integrated through #212. These are deliberately narrower than end-to-end recovery. Logical `pg_dump`, evidence binding/re-inspection, authenticated target isolation, post-restore application readiness, physical/WAL/PITR execution, external key custody, and measured RPO/RTO/HA/DR remain separate capability families.

## Current fitness matrix

| Documentation surface | Status | Fitness assessment | Required next action |
| --- | --- | --- | --- |
| `README.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Public entry point for standalone/embedded operation and tenant lifecycle. It is not the sole architecture or recovery authority. | Change only through its live owner when protected behavior changes. |
| `ARCHITECTURE.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Covers principal runtime boundaries but is separately owned by the active root-documentation lane. | Keep #229 out of this path; reconcile through the current owner. |
| `docs/product/PRD.md` | ACTIVE-PR | Canonical product contract now records #191 single-flight and #212 logical restore at their integrated bounded scope, while leaving broader worker/recovery guarantees unshipped. | Revalidate after each protected integration before changing status. |
| `docs/product/TRD.md` | ACTIVE-PR | Technical contract now separates transient session exclusion from durable leasing and integrated logical restore from backup, target authentication, catalog/application acceptance, and PITR. | Keep source/test authority stronger than prose. |
| ADR set | IMPLEMENTED-ON-PROTECTED-MAIN / record-local | Existing ADRs retain their own decision status. The restore-seek decision integrated with #212 is protected history; ADR status must not be inferred merely from neighboring active work. | Preserve record-local status and avoid number collisions. |
| `docs/adr/README.md` | ACTIVE-PR | Provides navigation and separates ADR decision status from implementation status. | Keep the index synchronized without embedding exact heads. |
| `docs/result-streaming.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Describes bounded result streaming/checkpoint behavior, not end-to-end exactly-once application. | Update only with integrated result-application changes. |
| `docs/remote-batch-lifecycle.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Operator authority for trusted tenant scope, standalone compatibility, forced RLS, direct-SQL limits, migration, and rollback. | Do not duplicate this contract into a competing operator guide. |
| PostgreSQL recovery evidence | IMPLEMENTED-ON-PROTECTED-MAIN / end-to-end PARTIAL | Receipt, artifact, and packaged-schema evidence are bounded content-free identity/integrity primitives. | Never promote hashes/receipts into restorability, target-isolation, PITR, or RPO/RTO claims. |
| PostgreSQL logical backup | ACTIVE-PR | #208 remains a bounded `pg_dump` candidate. | Keep unshipped until normal integration and final-head evidence. |
| PostgreSQL logical restore | IMPLEMENTED-ON-PROTECTED-MAIN / end-to-end PARTIAL | The logical restore executor is protected-main behavior through merged #212. Closed #209 remains historical defect evidence because its EOF-consumption postcondition was invalid for seekable custom-format archives. | Preserve caller-owned source trust, constrained libpq environment, transactional failure, metadata verification, target-isolation and post-restore acceptance gaps; do not imply RPO/RTO/PITR. |
| Recovery evidence binding and live re-inspection | ACTIVE-PR | Candidate seams compose or re-inspect bounded evidence; success is not provenance, restorability, or target isolation. | Keep branch evidence distinct from shipped truth. |
| Post-restore catalog/application acceptance | ACTIVE-PR | Catalog/application readiness must reject same-name decoys and prove the actual live PostgreSQL authority it claims. #296 remains a Draft branch candidate. | Promote only after protected integration of unchanged source and tests. |
| Permanent live PostgreSQL integration acceptance | ACTIVE-PR | #341 owns the hosted `pytest -m integration` lane. Its current branch and child #296 have branch-level GREEN evidence, not protected-main authority. | Preserve the permanent lane through protected integration; do not substitute deselected or mocked tests. |
| Physical/WAL/PITR recovery | ACTIVE-PR / PARTIAL | Current branches record bounded evidence and intent; they do not prove actual replay, promotion, or achieved objectives. | Require deployment-specific execution and measured acceptance before RPO/RTO claims. |
| Restore-target isolation | PARTIAL | Configuration/service-name separation is not authenticated cluster identity. Closed #225 is historical lineage only, not live authority. | Require authenticated target proof before production restore-safety claims. |
| Existing-volume legacy PostgreSQL retirement | ACTIVE-PR | Migration/operator work remains separate from already shipped tenant lifecycle. | Do not duplicate its README/architecture/operability surface here. |
| OpenTelemetry installation/operation documentation | ACTIVE-PR | Packaging-extra work remains an overlay until exact lock/install/release evidence integrates. | Keep base installs dependency-light. |
| Durable reconciliation candidate discovery | ACTIVE-PR | Discovery remains unshipped even though the bounded reconciliation primitive and transient session single-flight are protected behavior. | Preserve bounded deterministic tenant-qualified discovery requirements. |
| Tenant-qualified reconciliation single-flight | IMPLEMENTED-ON-PROTECTED-MAIN | #191 integrated the transient PostgreSQL session advisory-lock seam. It is not a scheduler, durable lease, result-application transaction, terminal-work-retirement mechanism, or distributed exactly-once guarantee. | Keep those non-goals explicit. |
| Atomic durable result application | ACTIVE-PR / end-to-end PARTIAL | Existing checkpoint/stream primitives do not prove complete exactly-once application; #194 remains active candidate work. | Require same-transaction local authority and preserve external-effect limits. |
| Runtime config/schema provisioning and secret policy | ACTIVE-PR / protected compatibility baseline | Protected main permits `SecretStore(require_encryption=False)` and compatibility rows with `is_encrypted = FALSE`; optional Fernet is supported, not mandated. #210 remains an active stricter runtime/operator-contract candidate. | Do not claim mandatory encryption, historical-row migration, rotation/recovery, or external key custody until those contracts integrate. |
| Canonical traceability | ACTIVE-PR | This overlay is the current canonical documentation landing vehicle. #226 and superseded #214 are historical documentation predecessors, not live authority. | Keep stable implementation/test/doc references and no exact heads. |
| Threat model | ACTIVE-PR | `docs/THREAT_MODEL.md` records assets, boundaries, attacker preconditions, mitigations, residual risk, and APA 7th NIST references without claiming certification. | Promote only through normal merge; update residual risk when runtime authority changes. |
| Data governance | ACTIVE-PR | `docs/DATA_GOVERNANCE.md` maps data classes, owners, tenant authority, retention/deletion limits, authorized-content fidelity, and optional Fernet compatibility. | Do not turn evidence readiness into a records-program certification. |
| UML/component/sequence views | ACTIVE-PR | `docs/uml/component-and-sequence.md` shows standalone/embedded composition and tenant-validation sequence. | Keep active-only components off shipped diagrams until integrated. |
| ERD / schema model | ACTIVE-PR | `docs/erd/package-owned-schema.md` maps packaged tables and migration-owned checkpoint identity. | SQL remains stronger authority; refresh only after integrated schema identity changes. |
| General standalone operator guide | PARTIAL | Operator guidance exists across README and topic authorities but no single omnibus `docs/OPERABILITY.md` is protected authority. | Consolidate only after checking adjacent writers. |
| Release governance | PARTIAL | Release-evidence code/workflows exist, but publication remains valid only from a fully accepted exact protected head. | Tie version, CHANGELOG, package, SBOM, provenance, reproducibility, rollback, tag and publication verification together through the release owner. |
| Licensing / third-party notices | PARTIAL | Apache-2.0 source licensing and SBOM evidence exist; acquisition diligence still needs a concise third-party notice process. | Add evidence without making legal-certification claims. |

## Non-negotiable documentation invariants

- Protected-main behavior is shipped authority; active PRs and historical branches are not.
- Exact contributor/protected heads, generated merge commits, run IDs, and queue state belong in PR/review evidence, not durable product documents.
- Standalone operation and modular embedding remain co-equal boundaries; no CWL host repository is a hidden runtime dependency.
- Tenant scope comes only from a trusted authenticated/authorized host selection. RLS is defense in depth, not authentication, SQL-injection prevention, or correct identity mapping.
- The standalone `DurableBatchAPIClient` retains its four-argument lifecycle-recorder seam and explicit `standalone` scope unless a reviewed compatibility change integrates.
- Provider/model content never becomes tenant, credential, endpoint, filesystem, or database authority.
- #191 proves only tenant-qualified transient session advisory single-flight; it does not prove a durable lease, scheduler, result-application transaction, terminal retirement, or distributed exactly-once semantics.
- #212 proves the bounded direct logical restore executor and corrected custom-format seek semantics; #209 remains historical EOF-defect evidence. The integrated executor does not prove backup creation, authenticated target isolation, post-restore catalog/application readiness, PITR, or RPO/RTO/HA/DR.
- Protected secret storage supports optional Fernet plus an explicit compatibility mode. Mandatory encrypted-at-rest policy, migration of compatibility rows, key rotation/recovery, and external custody are not inferred.
- Content-fidelity constraints do not prove end-to-end result application.
- Recovery receipts and hashes are evidence primitives, not restoration success.
- Security, privacy, SOC 2, and CSAP material is evidence readiness unless an external certification actually exists.
- Owned coverage, supported Python versions, packaging, SBOM/provenance, rollback, release and bounded-diagnostic requirements remain synchronized with live governance.

## Fitness gate for future canonical changes

Before changing a canonical surface, refetch protected main, open PRs, non-default branches, affected source/schema/test authorities, and adjacent documentation writers. Repair the earliest stale authority boundary without widening writer ownership. After a capability merges, update status only after reading the resulting protected tree; after a capability is superseded, keep historical lineage only where it explains a current constraint. Every changed documentation head must reacquire exact-head quality/security/release evidence and qualifying review under the then-live ruleset.
