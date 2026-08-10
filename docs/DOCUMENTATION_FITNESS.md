# Documentation fitness and authority

## Purpose

This document answers a simple acquisition-readiness question: **can a buyer, maintainer, security reviewer, or embedding team reconstruct pg-llm-batch from GitHub without reading old chat transcripts or reverse-engineering a chain of pull-request bodies?**

At the protected-main baseline used to open this documentation slice (`bf2cc2e140dc3ff4a56c3203f80f41bb9fed5d10`), the answer was **no**. `README.md` described the product and current runtime path, and `SECURITY.md` defined vulnerability-reporting policy, but the repository did not have a canonical PRD, TRD, root architecture, UML, ERD, threat model, test strategy, operability contract, traceability matrix, ADR index, or durable repository record for maintenance/evidence-authority decisions.

This branch establishes that canonical graph. Until this PR reaches protected `main`, every document introduced here is itself **ACTIVE-PR** documentation rather than protected-main authority.

## Closed documentation-fitness vocabulary

Use exactly these statuses when assessing a document family:

- **PRESENT-CURRENT** — present and consistent with the code/workflows/schema it claims to describe.
- **PRESENT-STALE** — present but contradicted by current protected-main behavior or an explicitly authoritative replacement.
- **PARTIAL** — useful but insufficient to reconstruct the contract without another source.
- **MISSING** — no canonical repository document exists for the required family.
- **NOT-APPLICABLE** — the family genuinely does not apply and the reason is documented.
- **SUPERSEDED** — retained only as historical evidence; another document is authoritative.

Document fitness is different from capability maturity. Use exactly these maturity states:

- **IMPLEMENTED-ON-PROTECTED-MAIN** — observable on the current protected default branch.
- **ACTIVE-PR** — implemented or documented only on an open pull request.
- **PARTIAL** — some runtime or evidence exists, but the target contract is incomplete.
- **ACCEPTED-ARCHITECTURE** — a reviewed target decision exists without complete protected-main implementation.
- **PLANNED** — implementation is intentionally future work.
- **RESEARCH-ONLY** — evidence or exploration exists without an accepted implementation decision.
- **SUPERSEDED** — replaced and not an active target.
- **OUT-OF-SCOPE** — explicitly excluded from the product boundary.

## Baseline fitness assessment

| Family | Protected-main baseline | This documentation PR | Notes |
| --- | --- | --- | --- |
| README / quick start | PRESENT-CURRENT | PRESENT-CURRENT | Strong runtime overview, but not a substitute for PRD/TRD/architecture. |
| Product PRD | MISSING | PRESENT-CURRENT | Added as `docs/product/PRD.md`; file maturity is ACTIVE-PR until merge. |
| Technical requirements | MISSING | PRESENT-CURRENT | Added as `docs/product/TRD.md`. |
| Public API / CLI / schema / version contract | PARTIAL | PRESENT-CURRENT | Added as `docs/product/API_CONTRACT.md`; explicitly separates protected-main exports/commands/schema from ACTIVE-PR overlays and defines Semantic Versioning/deprecation rules. |
| Root architecture | MISSING | PRESENT-CURRENT | Added as `ARCHITECTURE.md`; distinguishes protected-main as-built from active-PR overlay. |
| UML behavior/deployment views | MISSING | PRESENT-CURRENT | Added as code-renderable Mermaid in `docs/architecture/UML.md`. |
| ERD / logical data model | MISSING | PRESENT-CURRENT | Added from `pg_llm_batch/schema.sql`; active checkpoint/audit entities are separately labeled ACTIVE-PR. |
| Vulnerability reporting | PRESENT-CURRENT | PRESENT-CURRENT | `SECURITY.md` remains authoritative for disclosure process. |
| Threat model | MISSING | PRESENT-CURRENT | Added as `docs/THREAT_MODEL.md`; separates package and host responsibilities. |
| Data governance / privacy | PARTIAL | PRESENT-CURRENT | Protected main contains privacy-sensitive persistence and bounded telemetry/diagnostic rules but no canonical package-vs-host governance authority. `docs/DATA_GOVERNANCE.md` now classifies content/credentials/metadata, preserves purpose-bound utility instead of blanket masking, labels #53 tenant isolation and #71 provider-error confidentiality ACTIVE-PR, and makes retention/erasure/backup/residency host-owned unless a future accepted contract changes that boundary. |
| Test strategy | PARTIAL | PRESENT-CURRENT | Existing CI/pyproject encoded gates but no explanatory canonical strategy. |
| Operability / recovery | PARTIAL | PRESENT-CURRENT | README and doctoring covered fragments; a canonical runbook is added and now includes scheduler/control-plane failure recovery without conflating it with repository failure. |
| Release / rollback / provenance acceptance | PARTIAL | PRESENT-CURRENT | Added as `docs/RELEASE_ACCEPTANCE.md`; it keeps descriptor-pinned reproducibility itself ACTIVE-PR (#57) while defining exact integrated-head, migration, rollback, SBOM/provenance, protected-main post-merge operational, and post-publication gates. |
| Licensing / IP / third-party notices | PARTIAL | PRESENT-CURRENT | Protected main already declares Apache-2.0 through `pyproject.toml`, `LICENSE`, and `NOTICE`; `docs/LICENSING_AND_IP.md` adds the canonical acquisition-diligence boundary, third-party verification rule, and explicit non-substitution for legal/title review. |
| Traceability | MISSING | PRESENT-CURRENT | Added requirement/decision -> source/schema/test/evidence mapping, including scheduler failure recovery authority. |
| Product ADR index and foundational decisions | MISSING | PRESENT-CURRENT | `docs/adr/README.md` now indexes detailed protected-main foundation records for PostgreSQL/disk-free authority, provider HTTP/replay boundaries, standalone/host composition, and durable lifecycle observation; the new records themselves remain ACTIVE-PR documentation until #93 integrates. |
| Maintenance-governance ADRs | MISSING | PRESENT-CURRENT | Work conservation, evidence identity, writer lease, canonical-documentation authority, semantic review vs infrastructure/policy evidence separation (`docs/automation/ADR-0004-review-evidence-separation.md`), protected-main operational acceptance, and scheduler failure recovery are now durable. ADR-0006 classifies generic scheduler failures as control-plane incidents, preserves one authoritative enabled task, prevents duplicate schedulers, bounds prompt growth, and requires same-invocation repository continuation. |
| Code-owner review governance | PRESENT-CURRENT | PRESENT-CURRENT | Protected `AGENTS.md` records code-owner review gates as disabled and **on hold** for the current **solo-maintainer** organization state. ADR-0004, release acceptance, and traceability preserve that hold while keeping semantic/independent approval separate **where required** by live policy; canonical docs must not re-enable or universalize the held gate. |
| Scheduler failure recovery | MISSING | PRESENT-CURRENT | `docs/automation/ADR-0006-scheduler-failure-recovery.md`, `docs/OPERABILITY.md`, and `docs/TRACEABILITY.md` now define the generic scheduled-task-failure boundary, prompt compaction, duplicate-writer prevention, same-invocation handoff, rollback, and double-exit recovery contract. |
| Feature doctoring | PARTIAL | PRESENT-CURRENT | Keep feature-specific doctoring; index it through traceability rather than duplicating it. |
| AGENTS guidance | PARTIAL | PARTIAL | Protected main records the code-owner review hold but remains narrow overall. Consolidate broader guidance after overlapping active feature branches land rather than creating a conflict-heavy competing copy here. |
| CLAUDE guidance | MISSING | PARTIAL | Several active product branches carry guidance. Canonical reconciliation is deferred until their source contracts integrate; this does not replace the product documentation graph. |

## Product-capability maturity snapshot

This is a **dated classification aid for the current documentation branch**, not a release checklist and not a substitute for refetching live PR state before a merge/release decision.

### IMPLEMENTED-ON-PROTECTED-MAIN

- PostgreSQL `pg_tiktoken`-backed token counting and batch assembly.
- Disk-free JSONL persistence and reconstruction through PostgreSQL tables.
- OpenAI-compatible Files/Batches client with bounded request timeout, bounded control-plane JSON, bounded provider-file downloads, destination/resource validation, and bounded retries for the currently reviewed GET status set. Protected-main error translation at this baseline must not be described as already satisfying the stronger #71 provider-error confidentiality overlay.
- `DurableBatchAPIClient` with database-owned remote lifecycle observation ordering and persistence in `llm_remote_batch_jobs`.
- Database-backed configuration and secret storage (`com_config`, `com_secrets`) with optional Fernet encryption.
- Optional host-owned OpenTelemetry operation observability.
- CLI and standalone Docker Compose deployment.
- Current `/healthz` readiness implementation and current CI/packaging gates.
- Apache-2.0 package metadata and root `LICENSE`/`NOTICE` artifacts; release-specific dependency/license verification remains a separate evidence task.
- Code-owner review gates disabled (on hold) under protected `AGENTS.md` while the organization remains single-maintainer; this is governance state, not product behavior and not a waiver of other review evidence where required.

### ACTIVE-PR

Current material implementation/documentation owners include:

- #53 — tenant-isolated durable lifecycle state and PostgreSQL RLS boundary.
- #57 — descriptor-pinned reproducible release evidence.
- #58 — bounded incremental result-record streaming.
- #59 — resumable stream checkpoints.
- #60 — durable PostgreSQL checkpoint persistence.
- #92 — current linearized checkpoint OpenTelemetry observability replacement on #60.
- #94 — current linearized append-only checkpoint acceptance audit replacement on #92.
- #95 — current linearized atomic checkpoint migration operator replacement on #94.
- #96 — current linearized bounded checkpoint-audit pagination replacement on #95.
- #97 — current linearized bounded checkpoint-audit snapshot-manifest replacement on #96.
- #69 — hourly maintenance credential/writer-boundary hardening.
- #70 — readiness redaction, concurrency, timeout, and listener hardening.
- #71 — HTTP 425, permanent TLS/fingerprint, response-handoff, low-cardinality transport, and provider-error confidentiality hardening.
- #85 — secret input outside process argv.
- #86 — canonical typed configuration and mutable-state isolation.
- #87 — deterministic PostgreSQL connection ownership/cleanup plus strict no-key secret decode behavior.
- #88 — exact source-head CI evidence.
- #89 — explicit bootstrap-source precedence and blank-DSN rejection.
- #91 — loopback-only standalone Compose port publishing.
- #93 — this canonical documentation authority, data-governance/privacy authority, licensing/IP diligence authority, foundational protected-main ADR record set, protected-main operational-acceptance governance, scheduler failure recovery authority, and code-owner review-governance reconciliation.

Issue #90 is a **PLANNED** buyer-visible CLI cancellation slice whose implementation must wait until overlapping CLI/resource-lifecycle changes are protected or superseded.

### SUPERSEDED / stale-stack work

- #78 is SUPERSEDED by #92.
- #79 is SUPERSEDED by #94.
- #80 is SUPERSEDED by #95.
- #83 is SUPERSEDED by #96.
- #84 is SUPERSEDED by #97 and is closed unmerged. Historical checks/reviews from #84 do not transfer to #97.

The queue must be revalidated before any release or acquisition statement. Closed, merged, superseded, or replaced PRs move to their corresponding maturity state; this document must not preserve stale ACTIVE-PR claims indefinitely.

## Sufficiency judgement

The canonical documentation graph in this PR is now **structurally sufficient** for product intent, technical requirements, public API/CLI/schema compatibility, architecture, core data model, foundational product decisions, threat model, data governance/privacy, testing, operability, release/rollback/provenance acceptance, licensing/IP/third-party diligence, traceability, and the maintenance/evidence-governance decisions. The data-governance authority makes sensitive content/credential/metadata classification, package-vs-host responsibility, provider disclosure, telemetry/logging limits, retention/erasure/backup/residency ownership, and the ACTIVE-PR status of provider-error confidentiality explicit without inventing a legal-compliance claim or destructive blanket masking. The foundational ADR set makes the already-shipped PostgreSQL/disk-free, provider HTTP/replay, standalone/embedding-host, and lifecycle-observation choices reviewable as decisions rather than only as architecture prose. `docs/automation/ADR-0004-review-evidence-separation.md` makes semantic review versus infrastructure/policy evidence separation explicit, so infrastructure-only review failures remain fail-closed merge blockers without being misrepresented as source-code findings. It also reconciles the protected **code-owner review hold**: code-owner gates are disabled and on hold for the solo-maintainer state, while semantic or other independent approval remains separate where required by live policy and must not be inferred as universally mandatory. ADR-0005 makes source merge explicitly intermediate for runtime-sensitive changes and requires fresh capability-specific protected-main operational acceptance before incident/release closure where applicable. ADR-0006 now captures the repeated generic scheduler-failure and premature-stop pattern from this project conversation as a durable control-plane decision: scheduler failure is not repository failure, the enabled hourly task remains singular unless evidence justifies replacement, prompt size is bounded by compaction rather than unbounded append, scheduler repair hands back to repository work in the same invocation, and termination still requires the normal double exit sweep. The licensing/IP authority makes Apache-2.0 metadata, project provenance, NOTICE, dependency/SBOM verification, and repository-vs-external legal evidence boundaries explicit. This is a documentation sufficiency statement, not a claim that all ACTIVE-PR capabilities are implemented, that every third-party obligation has been independently cleared for a future release/transaction, or that the product is release-ready.

Two repository-guidance surfaces remain intentionally PARTIAL: `AGENTS.md` and `CLAUDE.md`. `AGENTS.md` already provides the protected code-owner hold but not the broader product/automation graph; multiple active implementation branches currently modify shared guidance files, so this docs-only branch does not create a competing canonical rewrite. They must be reconciled after the moving implementation stack stabilizes or merges. The fitness matrix keeps that incompleteness visible instead of hiding it.

## Authority rules

1. **Protected code beats documentation.** If this graph disagrees with the exact protected-main source/schema/workflow, the code is the immediate runtime truth and the document is PRESENT-STALE until repaired.
2. **Live base beats PR-body base metadata.** Stacked PRs require an independently resolved current base-ref tip before evidence is promoted.
3. **Active PRs are not shipped.** A reviewed branch may be technically complete and still remain ACTIVE-PR.
4. **Checks, reviews, and runtime behavior are separate evidence classes.** A green status is not an independent approval, a review is not a test run, and a synthetic merge commit is not automatically source-head evidence.
5. **Architecture is timeless; evidence is dated.** Stable contracts belong in PRD/TRD/Architecture/ADR. Run IDs and transient SHAs belong in PR bodies or evidence notes unless a historical incident requires them.
6. **Do not invent entities.** ERD/data-model documentation may include conceptual ACTIVE-PR entities only when the implementing PR actually contains them, and must label them separately from protected-main persistence.
7. **Documentation is a release gate, not a release bypass.** A complete graph does not waive CI, security, provenance, licensing, operational, data-governance, or review requirements where required by live policy.
8. **Volatile queue facts are bounded.** PR numbers in this file are a dated navigation snapshot; architectural meaning lives in capability names and ADR/TRD contracts, not in mutable PR identifiers.
9. **Semantic review and infrastructure/policy blockers remain distinct.** When required semantic evidence is unavailable, the semantic result abstains or is unavailable; the non-source blocker may still fail merge readiness but does not create a synthetic source finding.
10. **Code-owner gates follow live governance.** The protected code-owner review requirement is disabled and on hold for the solo-maintainer state. Do not infer it as a universal merge requirement, and do not re-enable it until authoritative governance changes; evaluate other independent approval only where required by the live policy.
11. **Licensing scanners do not create legal authority.** Package metadata, NOTICE, SBOMs, and automated license classification are evidence inputs; unknown ownership/license obligations remain unresolved until verified rather than being inferred as approved.
12. **Privacy controls do not create host authorization.** Package-side redaction, bounded telemetry, or future tenant RLS cannot substitute for host-selected purpose, identity, authorization, retention, erasure, backup, or residency policy.
13. **Source merge does not create operational closure.** Runtime-sensitive changes require fresh capability-specific protected-main acceptance evidence under ADR-0005 before incident/release closure where applicable.
14. **Scheduler failure is not repository failure.** A generic scheduled-task failure remains a control-plane incident until independently classified. Preserve one authoritative enabled scheduler, do not create a duplicate scheduler reflexively, compact prompt/control state instead of accumulating an unbounded incident transcript, resume safe repository work in the same invocation, and apply the normal double exit sweep before termination.

## Fitness maintenance loop

For every material runtime, schema, security, deployment, workflow, scheduler/control-plane, public-API, dependency/license, data-governance, review-governance, or release-contract change:

1. refetch protected main and the exact active PR head/base;
2. identify which canonical document family owns the changed contract;
3. update the smallest authoritative document and its traceability entry;
4. run the documentation fitness contract plus normal repository gates;
5. classify anything intentionally deferred as ACTIVE-PR, PLANNED, SUPERSEDED, or OUT-OF-SCOPE rather than leaving ambiguous prose; and
6. after the documentation mutation, return to executable product/merge/operational work instead of treating documentation as run completion.

## References

Apache Software Foundation. (2004). *Apache License, Version 2.0*. https://www.apache.org/licenses/LICENSE-2.0

GitHub. (2026). *Events that trigger workflows*. GitHub Docs. https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218