# Documentation Fitness

## Authority and status model

This inventory evaluates the documentation graph against the exact protected-main tree `d0a4b30be1f46536e352443309f3a35533156767`. It does not promote pull-request content into shipped truth. The canonical status vocabulary is shared with `docs/product/PRD.md` and `docs/product/TRD.md`: **IMPLEMENTED-ON-PROTECTED-MAIN**, **ACTIVE-PR**, **PARTIAL**, **PLANNED**, and **SUPERSEDED**.

A document is *fit* only when it states the correct authority boundary, is consistent with the protected-main code/schema/tests it describes, avoids transferring predecessor or active-branch evidence into shipped claims, and gives an operator or reviewer enough information to use, verify, recover, or reject the relevant behavior safely.

## Current fitness matrix

| Documentation surface | Status | Fitness assessment | Required next action |
| --- | --- | --- | --- |
| `README.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Useful public entry point, but it is not the sole product/architecture authority and must not absorb transient PR/check state. | Keep beginner-readable; update bounded shipped capability changes after merge. |
| `ARCHITECTURE.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Covers standalone/embedded deployment, durable tenancy/RLS, migration boundary, interoperability, and verification, but does not by itself form a complete system/UML/data model. | Keep architectural contracts synchronized; add separate UML/data views rather than overloading this file. |
| `docs/product/PRD.md` | ACTIVE-PR | First current-main-compatible canonical product contract. It explicitly separates shipped, active, partial, planned, and superseded capability states. | Validate exact-head docs gates and integrate only through normal PR governance. |
| `docs/product/TRD.md` | ACTIVE-PR | First current-main-compatible technical requirements authority; component boundaries and release/testing invariants are explicit. | Validate exact-head docs gates and integrate only through normal PR governance. |
| ADR set (`0002`, `0003`, `0004`, `0006`, `0007`, `0015`) | IMPLEMENTED-ON-PROTECTED-MAIN | Material tenant, release-evidence, result-checkpoint, and retry decisions exist, but there is no canonical ADR index describing numbering gaps, status, supersession, and protected-main applicability. | Add an ADR index on this canonical branch after checking active ADR writers. |
| `docs/result-streaming.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Describes bounded provider result streaming/checkpoint behavior; checkpoint persistence has a separate accepted ADR. | Update only when the integrated result-application contract changes the operator-facing boundary. |
| `docs/remote-batch-lifecycle.md` | IMPLEMENTED-ON-PROTECTED-MAIN | Durable lifecycle/tenant behavior has detailed protected-main documentation. | Keep synchronized with tenant/RLS and lifecycle migrations. |
| Topic-specific doctoring/reference docs | IMPLEMENTED-ON-PROTECTED-MAIN | Useful deep evidence exists, but doctoring material is supporting evidence, not the canonical product-status authority. | Keep primary-reference and APA-style citations current where material. |
| Existing-volume legacy PostgreSQL retirement operability material | ACTIVE-PR | PR #184 contains bounded migration/operator documentation, but it is not shipped and its exact-head acceptance remains separate. | Do not duplicate or rewrite #184-owned README/architecture/operability/retirement surfaces here. |
| OpenTelemetry installation/operation documentation | ACTIVE-PR | PR #175 owns the packaging-extra lane; protected main must not imply the optional dependency lock is integrated. | Promote only after exact lock/materialization and release gates are proven. |
| Durable reconciliation candidate/single-flight documentation | ACTIVE-PR | PRs #190 and #191 own current reconciliation additions; protected main has only the scheduler-independent bounded reconciliation primitive. | Update canonical shipped status only after each exact head merges. |
| Atomic durable result application | ACTIVE-PR | Draft #194 is RED-only at its initial head and is not product truth. Protected main still has a PARTIAL end-to-end result-application capability. | Keep PARTIAL until test-first implementation, exact-head gates, review, and merge complete. |
| Runtime config/schema provisioning separation | ACTIVE-PR / BLOCKED | Draft #193 is RED-only and currently frozen because a source-affecting no-PR config branch remains live writer evidence. | Do not describe the least-privilege runtime-store repair as shipped or proceed through competing source ownership. |
| Canonical traceability | ACTIVE-PR | This branch is establishing the first current-main-compatible requirements-to-evidence map. | Maintain `docs/TRACEABILITY.md` using stable code/test/doc authorities, not run IDs. |
| Threat model | PLANNED | No canonical protected-main `docs/THREAT_MODEL.md` is present. Security rules are distributed across AGENTS, architecture, ADRs, tests, and issue/PR evidence. | Add a threat model that distinguishes assets, trust boundaries, attacker capabilities, mitigations, residual risk, and non-guarantees without certification claims. |
| Data governance | PLANNED | No single canonical data-governance document currently maps data classes, retention/ownership, tenant authority, privacy exposure, backup/restore, and deletion limits. | Add a protected-main-grounded data-governance contract. |
| UML/component/sequence views | PLANNED | Root architecture is prose-first; no canonical UML authority is present. | Add textual Mermaid/PlantUML-compatible component and critical sequence diagrams after active source contracts stabilize. |
| ERD / schema model | PLANNED | SQL and schema tests are authoritative, but no canonical ERD summarizes package-owned identities, tenancy, checkpoint state, and relationships. | Generate/maintain an ERD from protected-main schema; label migration-only/active-PR objects separately. |
| Standalone operator guide | PARTIAL | Operational instructions exist across README and topic docs, while #184 is adding migration-specific operability. There is no protected-main general `docs/OPERABILITY.md`. | Establish a general operator authority without racing #184's bounded migration changes. |
| Release governance | PARTIAL | Release-evidence ADRs/tests/workflows are strong, but the canonical graph lacks one concise protected-main release/operator authority tying versioning, SBOM, provenance, artifact identity, rollback/recovery, and publication verification together. | Add a stable release contract after checking active release writers; do not copy workflow-run IDs. |
| Licensing / third-party notices | PARTIAL | Apache-2.0 source headers and repository licensing exist, but acquisition diligence should explicitly trace package license, dependency/SBOM evidence, and third-party notice process. | Evaluate a concise licensing/compliance evidence index without claiming legal certification. |

## Non-negotiable documentation invariants

- Protected-main behavior is the shipped authority. Active PRs and historical branches are overlays, not proof of implementation.
- Exact contributor heads, generated merge commits, check IDs, and transient queue state belong in PR/review evidence, not durable architecture/product documents.
- Standalone operation and modular MSA embedding must be documented as co-equal supported boundaries; no ContextualWisdomLab host is a hidden runtime requirement.
- Tenant scope is selected only by a trusted authenticated/authorized host boundary. PostgreSQL RLS is defense in depth, not authentication or SQL-injection prevention.
- Provider/model content never becomes tenant, credential, endpoint, filesystem, or database authority.
- Distributed exactly-once processing is never implied by PostgreSQL checkpoint atomicity alone.
- Security, privacy, SOC 2, and CSAP material is evidence-readiness documentation only unless an external certification actually exists.
- Database object names, migration/rollback behavior, exact owned coverage requirements, Python-version acceptance, packaging/SBOM/provenance expectations, and bounded diagnostics must remain synchronized with repository tests and live governance.

## Fitness gate for future canonical changes

Before changing a canonical surface, refetch protected main, open PRs, non-default branches, the exact affected source/schema/test authorities, and any adjacent documentation writer. A documentation repair must not race a source-affecting writer whose behavior is still unsettled. After a product PR merges, update the canonical status classification from `ACTIVE-PR` or `PARTIAL` only when the protected-main tree contains the capability and the integrated evidence contract remains valid.