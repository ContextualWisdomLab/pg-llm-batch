# Documentation Fitness

## Authority and status model

This inventory evaluates canonical documentation against live protected-default-branch behavior. It deliberately does not freeze an exact protected SHA: exact heads and run IDs belong in PR/review evidence, while durable documentation records capability contracts. Status vocabulary is **IMPLEMENTED-ON-PROTECTED-MAIN**, **ACTIVE-PR**, **PARTIAL**, **PLANNED**, and **SUPERSEDED**.

A document is fit only when it agrees with protected code/schema/tests, preserves non-guarantees, keeps branch evidence out of shipped claims, and gives operators/reviewers enough information to use or reject the behavior safely.

Protected main contains the tenant lifecycle/RLS contract, bounded reconciliation, tenant-qualified transient session single-flight integrated through #191, bounded recovery-evidence primitives integrated through #205/#206/#207, bounded direct logical restore integrated through #212, and bounded restore-target name+cluster-identity verification integrated through merged #228. These are narrower than a complete worker or recovery product.

## Current fitness matrix

| Documentation surface | Status | Fitness assessment | Required next action |
| --- | --- | --- | --- |
| `README.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Public entry point for standalone/embedded operation. | Change through its live owner when protected behavior changes. |
| `ARCHITECTURE.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Root architecture is separately owned by the active root-documentation lane. | Keep this PR out of that path. |
| `docs/product/PRD.md` | ACTIVE-PR | Canonical product contract records merged #191, #212, and #228 only at their bounded protected scope. | Revalidate from protected source after every integration. |
| `docs/product/TRD.md` | ACTIVE-PR | Separates transient session exclusion from durable leasing; restore execution from backup/application/PITR; and cluster-identity comparison from connection provenance/authorization. | Keep source/test authority stronger than prose. |
| ADR set | IMPLEMENTED-ON-PROTECTED-MAIN / record-local | ADR 0016 governs custom-format restore seek semantics; ADR 0022 governs restore-target name+cluster identity separation. Other ADRs retain their own status. | Preserve record-local status and collision-free identifiers. |
| `docs/adr/README.md` | ACTIVE-PR | Navigation/status index without exact-head authority. | Keep synchronized with protected ADR files. |
| Tenant lifecycle operator material | IMPLEMENTED-ON-PROTECTED-MAIN | Trusted tenant selection, standalone compatibility, forced RLS, direct-SQL limits, migration, and rollback are documented. | Do not duplicate into competing operator guides. |
| PostgreSQL recovery evidence | IMPLEMENTED-ON-PROTECTED-MAIN / end-to-end PARTIAL | Receipt/artifact/schema evidence is bounded content-free identity/integrity evidence. | Do not infer restorability, provenance, PITR, or RPO/RTO. |
| PostgreSQL logical backup | ACTIVE-PR | #208 remains a `pg_dump` candidate. | Keep unshipped until normal integration. |
| PostgreSQL logical restore | IMPLEMENTED-ON-PROTECTED-MAIN / end-to-end PARTIAL | The logical restore executor is protected-main behavior through merged #212; #209 is historical EOF-defect evidence. | Preserve source trust, environment, transaction, metadata, target, and application-readiness boundaries. |
| PostgreSQL restore-target cluster identity verification | IMPLEMENTED-ON-PROTECTED-MAIN / end-to-end PARTIAL | Merged #228 supplies exact service-name plus caller-owned `system_identifier` separation. Same-cluster aliases fail closed. The package does not open/authenticate the connections, execute restore, or prove application/PITR/RPO-RTO readiness. Closed #225 is predecessor lineage only. | Treat the verifier as a bounded precondition, not end-to-end restore authorization. |
| Recovery evidence binding / live reinspection | ACTIVE-PR | Candidate composition/reinspection is not provenance or restore proof. | Keep branch evidence distinct from shipped truth. |
| Post-restore catalog/application acceptance | ACTIVE-PR | #296 is an application-readiness candidate. | Require protected integration before shipped claims. |
| Permanent live PostgreSQL integration acceptance | ACTIVE-PR | #341 owns the branch-level full integration-marker lane and currently tests #296 as a child. | Preserve the lane through normal integration; no mocks/deselection substitution. |
| Physical/WAL/PITR recovery | ACTIVE-PR / PARTIAL | Intent/evidence does not prove replay/promotion or achieved objectives. | Require deployment-specific execution and measurement. |
| Existing-volume legacy extension retirement | ACTIVE-PR | Separate migration/operator work. | Do not conflate with tenant lifecycle. |
| Durable reconciliation discovery | ACTIVE-PR | Discovery remains unshipped. | Keep tenant-qualified/bounded/deterministic authority. |
| Tenant-qualified reconciliation single-flight | IMPLEMENTED-ON-PROTECTED-MAIN | #191 is transient PostgreSQL session advisory locking only. | Never call it a scheduler, durable lease, result-app transaction, terminal-retirement authority, or distributed exactly-once mechanism. |
| Atomic durable result application | ACTIVE-PR / end-to-end PARTIAL | Checkpoint/stream primitives do not prove complete result application. | Keep external-effect limits explicit. |
| Runtime config/schema provisioning and secret policy | ACTIVE-PR / protected compatibility baseline | Protected main permits optional Fernet and `is_encrypted = FALSE` compatibility rows; #210 is stricter active work. | Do not claim mandatory encryption, historical-row migration, rotation/recovery, or external custody. |
| Canonical traceability | ACTIVE-PR | This overlay is the current canonical documentation landing vehicle; #226 and superseded #214 are historical predecessors. | Use stable implementation/test/doc authorities, not exact heads. |
| Threat model | ACTIVE-PR | Assets, boundaries, mitigations, residual risk, and NIST evidence are documented without certification claims. | Keep residual risk synchronized with protected authority. |
| Data governance | ACTIVE-PR | Data classes, owners, retention/deletion, content fidelity, and optional Fernet compatibility are explicit. | Do not turn evidence readiness into certification. |
| UML/component/sequence views | ACTIVE-PR | Standalone/embedded and tenant-validation views exist. | Keep branch-only components off shipped diagrams. |
| ERD / schema model | ACTIVE-PR | Packaged schema and migration-owned checkpoint identity are mapped. | SQL remains stronger authority. |
| Release governance | PARTIAL | Release evidence exists; immutable publication requires the exact accepted protected head. | Tie version, CHANGELOG, package, SBOM, provenance, rollback, tag, and publication verification together through release ownership. |

## Non-negotiable documentation invariants

- Protected-main behavior is shipped authority; active PRs and historical branches are not.
- Exact SHAs, generated merge commits, run IDs, and queue state stay in PR/review evidence.
- Standalone and modular embedding remain co-equal boundaries.
- `tenant_scope` comes from a trusted authenticated/authorized host; RLS is defense in depth, not authentication.
- #191 proves transient tenant-qualified session single-flight, not durable leasing or exactly-once.
- #212 proves bounded direct logical restore with corrected custom-format seek semantics, not backup, application readiness, PITR, or RPO/RTO.
- #228 proves only that supplied exact service names and caller-owned PostgreSQL `system_identifier` values differ. It does not authenticate the connections or collector, execute restore, or prove post-restore application readiness.
- Optional Fernet plus explicit compatibility mode is protected behavior; mandatory encryption/migration/rotation/custody is not inferred.
- Recovery evidence and command success are not equivalent to recovery success.
- SOC 2/CSAP/security/privacy material remains evidence readiness absent external certification.

## Fitness gate

Before changing a canonical surface, refetch protected main, open PRs, affected source/schema/tests, current ADRs, and adjacent writers. Repair the earliest stale authority boundary without widening ownership. After a merge, refresh status only from the resulting protected tree; after supersession, retain predecessor context only where it explains a live constraint. Every changed documentation head must reacquire then-required exact-head quality/security/release evidence and qualifying review.
