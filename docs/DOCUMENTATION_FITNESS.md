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
| Root architecture | MISSING | PRESENT-CURRENT | Added as `ARCHITECTURE.md`; distinguishes protected-main as-built from active-PR overlay. |
| UML behavior/deployment views | MISSING | PRESENT-CURRENT | Added as code-renderable Mermaid in `docs/architecture/UML.md`. |
| ERD / logical data model | MISSING | PRESENT-CURRENT | Added from `pg_llm_batch/schema.sql`; active checkpoint/audit entities are separately labeled ACTIVE-PR. |
| Vulnerability reporting | PRESENT-CURRENT | PRESENT-CURRENT | `SECURITY.md` remains authoritative for disclosure process. |
| Threat model | MISSING | PRESENT-CURRENT | Added as `docs/THREAT_MODEL.md`; separates package and host responsibilities. |
| Test strategy | PARTIAL | PRESENT-CURRENT | Existing CI/pyproject encoded gates but no explanatory canonical strategy. |
| Operability / recovery | PARTIAL | PRESENT-CURRENT | README and doctoring covered fragments; a canonical runbook is added. |
| Traceability | MISSING | PRESENT-CURRENT | Added requirement/decision -> source/schema/test/evidence mapping. |
| Product ADR index | MISSING | PRESENT-CURRENT | Added as `docs/adr/README.md`; active-PR ADRs remain explicitly unshipped. |
| Maintenance-governance ADRs | MISSING | PRESENT-CURRENT | Work conservation, evidence identity, and writer lease were previously chat/prompt-only. |
| Feature doctoring | PARTIAL | PRESENT-CURRENT | Keep feature-specific doctoring; index it through traceability rather than duplicating it. |
| AGENTS guidance | PARTIAL | PARTIAL | Protected main records only a narrow code-owner hold. Consolidate after overlapping active feature branches land rather than creating a conflict-heavy competing copy here. |
| CLAUDE guidance | MISSING | PARTIAL | Several active product branches carry guidance. Canonical reconciliation is deferred until their source contracts integrate; this does not replace the product documentation graph. |
| API / schema / version contract | PARTIAL | PARTIAL | Public exports, CLI behavior, schema, and package metadata are specified across PRD/TRD/Architecture/ERD. A dedicated versioned API/schema contract remains a follow-up fitness improvement rather than an undocumented assumption. |
| Release / rollback / provenance | PARTIAL | PARTIAL | Protected main builds packages; descriptor-pinned reproducible release evidence remains ACTIVE-PR (#57). Operability/Test Strategy document current rollback and acceptance boundaries without claiming publication readiness. |

## Product-capability maturity snapshot

This is a **dated classification aid for the current documentation branch**, not a release checklist and not a substitute for refetching live PR state before a merge/release decision.

### IMPLEMENTED-ON-PROTECTED-MAIN

- PostgreSQL `pg_tiktoken`-backed token counting and batch assembly.
- Disk-free JSONL persistence and reconstruction through PostgreSQL tables.
- OpenAI-compatible Files/Batches client with bounded request timeout, bounded control-plane JSON, bounded provider-file downloads, destination/resource validation, and bounded retries for the currently reviewed GET status set.
- `DurableBatchAPIClient` with database-owned remote lifecycle observation ordering and persistence in `llm_remote_batch_jobs`.
- Database-backed configuration and secret storage (`com_config`, `com_secrets`) with optional Fernet encryption.
- Optional host-owned OpenTelemetry operation observability.
- CLI and standalone Docker Compose deployment.
- Current `/healthz` readiness implementation and current CI/packaging gates.

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
- #69 — hourly maintenance credential/writer-boundary hardening.
- #70 — readiness redaction, concurrency, timeout, and listener hardening.
- #71 — HTTP 425 and permanent TLS/fingerprint retry-classification hardening.
- #85 — secret input outside process argv.
- #86 — canonical typed configuration and mutable-state isolation.
- #87 — deterministic PostgreSQL connection ownership/cleanup.
- #88 — exact source-head CI evidence.
- #89 — explicit bootstrap-source precedence and blank-DSN rejection.
- #91 — loopback-only standalone Compose port publishing.
- #93 — this canonical documentation authority.

Issue #90 is a **PLANNED** buyer-visible CLI cancellation slice whose implementation must wait until overlapping CLI/resource-lifecycle changes are protected or superseded.

### SUPERSEDED / stale-stack work

- #78 is SUPERSEDED by #92.
- #79 is SUPERSEDED by #94.
- #80 is SUPERSEDED by #95.
- #83 is SUPERSEDED by #96.
- #84 is still a stale descendant of closed #83 and therefore is not a valid canonical next stack boundary. Its unique snapshot-manifest delta must be replayed or otherwise safely replaced on the exact current #96 head before #84 can be closed as SUPERSEDED. Historical checks/reviews from #84 do not transfer.

The queue must be revalidated before any release or acquisition statement. Closed, merged, superseded, or replaced PRs move to their corresponding maturity state; this document must not preserve stale ACTIVE-PR claims indefinitely.

## Sufficiency judgement

The documentation graph in this PR is now **structurally sufficient for product intent, technical requirements, architecture, core data model, threat model, testing, operability, traceability, and the two maintenance/evidence-governance decisions**. It is not yet the final acquisition package because two families remain intentionally PARTIAL:

1. a dedicated versioned public API/schema compatibility contract; and
2. a dedicated release/rollback/provenance contract once the active reproducibility implementation is integrated.

Those gaps are explicit rather than hidden, so they can drive bounded follow-up work without overclaiming current protected-main behavior. AGENTS/CLAUDE consolidation is also intentionally deferred until overlapping implementation branches stop moving.

## Authority rules

1. **Protected code beats documentation.** If this graph disagrees with the exact protected-main source/schema/workflow, the code is the immediate runtime truth and the document is PRESENT-STALE until repaired.
2. **Live base beats PR-body base metadata.** Stacked PRs require an independently resolved current base-ref tip before evidence is promoted.
3. **Active PRs are not shipped.** A reviewed branch may be technically complete and still remain ACTIVE-PR.
4. **Checks, reviews, and runtime behavior are separate evidence classes.** A green status is not an independent approval, a review is not a test run, and a synthetic merge commit is not automatically source-head evidence.
5. **Architecture is timeless; evidence is dated.** Stable contracts belong in PRD/TRD/Architecture/ADR. Run IDs and transient SHAs belong in PR bodies or evidence notes unless a historical incident requires them.
6. **Do not invent entities.** ERD/data-model documentation may include conceptual ACTIVE-PR entities only when the implementing PR actually contains them, and must label them separately from protected-main persistence.
7. **Documentation is a release gate, not a release bypass.** A complete graph does not waive CI, security, provenance, operational, or independent-review requirements.
8. **Volatile queue facts are bounded.** PR numbers in this file are a dated navigation snapshot; architectural meaning lives in capability names and ADR/TRD contracts, not in mutable PR identifiers.

## Fitness maintenance loop

For every material runtime, schema, security, deployment, workflow, public-API, or release-contract change:

1. refetch protected main and the exact active PR head/base;
2. identify which canonical document family owns the changed contract;
3. update the smallest authoritative document and its traceability entry;
4. run the documentation fitness contract plus normal repository gates;
5. classify anything intentionally deferred as ACTIVE-PR, PLANNED, SUPERSEDED, or OUT-OF-SCOPE rather than leaving ambiguous prose; and
6. after the documentation mutation, return to executable product/merge/operational work instead of treating documentation as run completion.

## References

GitHub. (2026). *Events that trigger workflows*. GitHub Docs. https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218
