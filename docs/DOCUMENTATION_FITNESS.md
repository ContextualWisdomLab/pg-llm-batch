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
| Technical requirements | MISSING | PRESENT-CURRENT | Added as `docs/product/TRD.md`; #106 operation-span failure-status and #119 PostgreSQL logging privacy semantics are explicitly ACTIVE-PR, while PostgreSQL image reproducibility Issue #118 and container-native logging Issue #120 remain PLANNED rather than shipped. |
| Public API / CLI / schema / version contract | PARTIAL | PRESENT-CURRENT | Added as `docs/product/API_CONTRACT.md`; explicitly separates protected-main exports/commands/schema from ACTIVE-PR overlays and defines Semantic Versioning/deprecation rules, including #104 runtime typing and #105 structured exception snapshot semantics without shipped or immutability overclaims. |
| Root architecture | MISSING | PRESENT-CURRENT | Added as `ARCHITECTURE.md`; distinguishes protected-main as-built from active-PR overlay. |
| UML behavior/deployment views | MISSING | PRESENT-CURRENT | Added as code-renderable Mermaid in `docs/architecture/UML.md`. |
| ERD / logical data model | MISSING | PRESENT-CURRENT | Added from `pg_llm_batch/schema.sql`; active checkpoint/audit entities are separately labeled ACTIVE-PR. |
| Vulnerability reporting | PRESENT-CURRENT | PRESENT-CURRENT | `SECURITY.md` remains authoritative for disclosure process. |
| Threat model | MISSING | PRESENT-CURRENT | Added as `docs/THREAT_MODEL.md`; separates package and host responsibilities, classifies #105 caller-owned error-evidence alias drift, #106 description-free operation-span Error status, and #119 persistent-vs-volatile PostgreSQL query-text exposure without overclaiming content-free telemetry. |
| Data governance / privacy | PARTIAL | PRESENT-CURRENT | `docs/DATA_GOVERNANCE.md` classifies content/credentials/metadata and preserves purpose-bound utility instead of blanket masking. #119 adds selective-disclosure defaults for optional PostgreSQL logging/statistics while keeping `pg_stat_activity` live query text and privileged visibility explicit; retention/erasure/backup/residency remain host-owned unless an accepted contract moves them. |
| Test strategy | PARTIAL | PRESENT-CURRENT | Existing CI/pyproject encoded gates but no explanatory canonical strategy. |
| Operability / recovery | PARTIAL | PRESENT-CURRENT | README and doctoring covered fragments; a canonical runbook is added and now includes scheduler/control-plane failure recovery, user redirection, and silent-completion handling without conflating them with repository failure. Issue #120 separately tracks a container-native, storage-bounded PostgreSQL logging lifecycle after #119. |
| Release / rollback / provenance acceptance | PARTIAL | PRESENT-CURRENT | Added as `docs/RELEASE_ACCEPTANCE.md`; it keeps descriptor-pinned reproducibility itself ACTIVE-PR (#57) while defining exact integrated-head, migration, rollback, SBOM/provenance, protected-main post-merge operational, and post-publication gates. |
| Licensing / IP / third-party notices | PARTIAL | PRESENT-CURRENT | Protected main already declares Apache-2.0 through `pyproject.toml`, `LICENSE`, and `NOTICE`; `docs/LICENSING_AND_IP.md` adds the canonical acquisition-diligence boundary, third-party verification rule, and explicit non-substitution for legal/title review. |
| Traceability | MISSING | PRESENT-CURRENT | Added requirement/decision -> source/schema/test/evidence mapping, including scheduler failure recovery, the compact prompt source, public runtime hardening, #116/#117 argv privacy gaps, #118 PostgreSQL image reproducibility, #119 PostgreSQL logging privacy, and #120 logging operability. |
| Product ADR index and foundational decisions | MISSING | PRESENT-CURRENT | `docs/adr/README.md` now indexes detailed protected-main foundation records for PostgreSQL/disk-free authority, provider HTTP/replay boundaries, standalone/host composition, and durable lifecycle observation; the new records themselves remain ACTIVE-PR documentation until #93 integrates. |
| Maintenance-governance ADRs | MISSING | PRESENT-CURRENT | Work conservation, evidence identity, writer lease, canonical-documentation authority, semantic review vs infrastructure/policy evidence separation (`docs/automation/ADR-0004-review-evidence-separation.md`), protected-main operational acceptance, and scheduler failure recovery are now durable. ADR-0006 classifies generic scheduler failures and silent completion as control-plane incidents, preserves one authoritative enabled task, prevents duplicate schedulers, bounds prompt growth, prohibits prompt-only recovery, and requires same-invocation material repository continuation. |
| Compact hourly writer prompt | MISSING | PRESENT-CURRENT | `docs/automation/HOURLY_WRITER_PROMPT.md` is the discoverable **compact hourly writer prompt** source. A contract limits it to 8,000 UTF-8 bytes, rejects transient full commit identities, and preserves exact writer/evidence/merge/continuation semantics; actual external scheduler activation remains separate live evidence. |
| Code-owner review governance | PRESENT-CURRENT | PRESENT-CURRENT | Protected `AGENTS.md` records code-owner review gates as disabled and **on hold** for the current **solo-maintainer** organization state. ADR-0004, release acceptance, and traceability preserve that hold while keeping semantic/independent approval separate **where required** by live policy; canonical docs must not re-enable or universalize the held gate. |
| Scheduler failure recovery | MISSING | PRESENT-CURRENT | `docs/automation/ADR-0006-scheduler-failure-recovery.md`, `docs/OPERABILITY.md`, `docs/TRACEABILITY.md`, UML, and the compact prompt source now define generic scheduled-task failure, **silent completion**, empty user-visible output, user redirection, prompt compaction, duplicate-writer prevention, same-invocation **material safe repository action**, exact exit evidence, rollback, and double-exit recovery. |
| PostgreSQL logging privacy | PARTIAL | PRESENT-CURRENT | ACTIVE-PR #119 hardens `docker/postgres/postgresql.conf.custom` and doctoring: persistent SQL/bind logging and `pg_stat_statements` retention are disabled by default, while bounded volatile `pg_stat_activity` query text and `pg_read_all_stats`/superuser access remain explicit residual trust boundaries. |
| PostgreSQL logging operability | PARTIAL | PRESENT-CURRENT | Issue #120 is PLANNED after #119: make the container path container-native and storage-bounded, distinguish rotation from retention, and preserve the #119 privacy boundary while allowing host-owned logging lifecycle controls. |
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
- Optional host-owned OpenTelemetry operation observability. Protected main does not yet include #106's explicit propagated-failure span Error status overlay.
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
- #70 — readiness redaction, bounded concurrency/read timeout, exact listener validation, and exec-form no-shell container command authority.
- #71 — HTTP 425/TLS/response-handoff hardening, bounded transport/provider-error confidentiality, and exact-input gateway authority.
- #85 — secret input outside process argv.
- #86 — canonical typed configuration and mutable-state isolation.
- #87 — deterministic PostgreSQL connection ownership/cleanup, strict no-key Base64/UTF-8 decode, and bounded wrong-key Fernet failure.
- #88 — exact source-head CI evidence.
- #89 — explicit bootstrap-source precedence and blank-DSN rejection.
- #91 — loopback-only standalone Compose publishing with a complete published-service allow-list.
- #93 — this canonical documentation authority, data-governance/privacy authority, licensing/IP diligence authority, foundational protected-main ADR record set, protected-main operational-acceptance governance, scheduler failure recovery authority, compact hourly writer prompt source, and code-owner review-governance reconciliation.
- #101 — fail-closed retirement of the legacy direct-SQL `pg_cron` + `pgsql-http` provider retriever while preserving historical retrieval logs, removing fresh-install `pg_cron`/`http` extension grants, and keeping provider network/credential authority in the Python client layer.
- #104 — public `BatchRequest` exact-runtime-type validation and rejected-value-confidentiality hardening; public compatibility remains ACTIVE-PR until protected integration.
- #105 — **structured error evidence** constructor-time shallow snapshots for `PgLlmBatchError.details` and `GatewayError.response_data`; this prevents outer caller-alias drift but is not immutable, deep-copied, append-only, or durable audit evidence.
- #106 — **operation span** failure-status semantics: propagated failures set OpenTelemetry Error without a description, successful operations keep status Unset, and status construction/mutation failures remain fail-open telemetry; this remains ACTIVE-PR until protected integration.
- #114 — deterministic repository **uv toolchain** pin via root `uv.toml`, preventing setup-uv latest-version drift while preserving runtime dependency and package-version semantics.
- #119 — **PostgreSQL logging privacy** for the optional monitoring config: persistent SQL/bind logging and `pg_stat_statements` retention off by default, bounded volatile `pg_stat_activity` query text explicitly governed, and no blanket masking/compliance claim.

### PLANNED

- Issue #107 — planned first-class **OpenTelemetry optional dependency** and live-conformance package contract after #57 and #106 settle; the base package remains free of a mandatory OpenTelemetry dependency until that separately reviewed slice integrates.
- Issue #108 — planned **endpoint-qualified tokenizer** metadata authority so identical model IDs on different endpoints cannot silently select the wrong tokenizer; implementation must preserve endpoint/model identity and fail closed on ambiguous metadata.
- Issue #109 — planned release-integrity consolidation onto a **single authoritative version** source, with machine-checked agreement across package metadata, runtime `__version__`, built artifacts, release tags, and release evidence.
- Issue #112 — planned typed-package `py.typed` marker and reproducible wheel/sdist/install package-data evidence after #57/#53 settle.
- Issue #113 — planned reconciliation of declared `Requires-Python` compatibility with the tested release matrix; Python 3.14 remains mandatory and unsupported claimed minors must not be silently skipped.
- Issue #115 — planned lock/governance for CI-only Python **quality tools** after #114/#88/#57 settle, binding coverage/docstring tooling versions into reviewed supply-chain evidence.
- Issue #116 — planned `count-tokens` prompt-content input outside process argv using one bounded non-argv authority, with deterministic UTF-8/newline semantics and no rejected prompt reflection; implementation waits for #85/#87 CLI/resource ownership.
- Issue #117 — planned credential-bearing PostgreSQL DSN input outside process argv, preserving #89 source precedence and #87 connection validation/ownership while rejecting unsafe values before libpq where package-owned.
- Issue #118 — planned reproducible **PostgreSQL image** inputs: deterministic Debian source/package versions, exact `pg_tiktoken` source+patch identity, and reviewed immutable Cargo dependency evidence; implementation waits for the active #94→#97 PostgreSQL Dockerfile stack and must compose with #101/#103 rather than race them.
- Issue #120 — planned **container-native**, **storage-bounded** PostgreSQL logging after #119 settles the privacy-safe event/content surface. It must preserve #119, allow runtime/platform log routing, distinguish rotation from **retention**, and keep storage lifecycle policy deployment-owned rather than implying PostgreSQL file rotation is deletion.
- Issue #90 — buyer-visible CLI cancellation after overlapping CLI/resource-ownership work settles.
- Issue #98 — reject malformed provider progress and non-finite control JSON after the overlapping #71 provider-control surface settles.
- Issue #99 — remove the shared default PostgreSQL credential from standalone Compose after #91 establishes the authoritative publishing boundary.
- Issue #100 — make component-image operating-system dependency resolution reproducible after #70 establishes the authoritative Dockerfile command/readiness boundary.
- Issue #102 — restore automatic provider reconciliation through the validated Python boundary after #101 retires direct-SQL provider HTTP; do not resurrect database-held provider network authority or claim distributed exactly-once delivery.
- Issue #103 — remove legacy `pg_cron`/`http` image packages and preload/configuration only after an existing-volume migration proves exact-job cleanup, dependency-safe extension removal, startup, rollback, and recovery; do not make package removal a leaf workaround for old-volume compatibility.

### SUPERSEDED / stale-stack work

- #78 is SUPERSEDED by #92.
- #79 is SUPERSEDED by #94.
- #80 is SUPERSEDED by #95.
- #83 is SUPERSEDED by #96.
- #84 is SUPERSEDED by #97 and is closed unmerged. Historical checks/reviews from #84 do not transfer to #97.

The queue must be revalidated before any release or acquisition statement. Closed, merged, superseded, or replaced PRs move to their corresponding maturity state; this document must not preserve stale ACTIVE-PR claims indefinitely.

## Sufficiency judgement

The canonical documentation graph in this PR is now **structurally sufficient** for product intent, technical requirements, public API/CLI/schema compatibility, architecture, core data model, foundational product decisions, threat model, data governance/privacy, testing, operability, release/rollback/provenance acceptance, licensing/IP/third-party diligence, traceability, and the maintenance/evidence-governance decisions. The data-governance authority makes sensitive content/credential/metadata classification, package-vs-host responsibility, provider disclosure, telemetry/logging limits, retention/erasure/backup/residency ownership, and the ACTIVE-PR status of provider-error confidentiality, structured error evidence, and PostgreSQL logging privacy explicit without inventing a legal-compliance, immutability, content-free-telemetry, or audit-record claim. The foundational ADR set makes the already-shipped PostgreSQL/disk-free, provider HTTP/replay, standalone/embedding-host, and lifecycle-observation choices reviewable as decisions rather than only as architecture prose. `docs/automation/ADR-0004-review-evidence-separation.md` makes semantic review versus infrastructure/policy evidence separation explicit, so infrastructure-only review failures remain fail-closed merge blockers without being misrepresented as source-code findings. It also reconciles the protected **code-owner review hold**: code-owner gates are disabled and on hold for the solo-maintainer state, while semantic or other independent approval remains separate where required by live policy and must not be inferred as universally mandatory. ADR-0005 makes source merge explicitly intermediate for runtime-sensitive changes and requires fresh capability-specific protected-main operational acceptance before incident/release closure where applicable. ADR-0006 captures the repeated generic scheduler-failure and premature-stop pattern from this project conversation as a durable control-plane decision: scheduler failure is not repository failure; **silent completion** and **empty user-visible output** are not success evidence; user redirection must refetch the queue and resume a **material safe repository action** when one exists; prompt repair alone is not recovery; the enabled hourly task remains singular unless evidence justifies replacement; prompt size is bounded by compaction rather than unbounded append; and termination still requires exact no-work evidence from the normal double exit sweep. `docs/automation/HOURLY_WRITER_PROMPT.md` turns that decision into a discoverable, bounded, machine-checked **compact hourly writer prompt** while explicitly leaving actual external scheduler state as a separate live evidence class. The public contract/TRD/Threat Model/Data Governance/Traceability graph distinguishes #105's constructor-time shallow snapshot from immutable or durable audit evidence, so the exception-integrity target can be reviewed without overclaiming its assurance level. The TRD/Threat Model/Traceability graph also classifies #106's **operation span** Error-status target without promoting it to shipped behavior: failures become queryable without status descriptions or automatic exception recording, success remains Unset, and ordinary telemetry status failures cannot replace the application result. #119 now similarly distinguishes persistent log/statistics copies from volatile privileged `pg_stat_activity` query text, while Issue #120 carries the separate container-native storage/retention lifecycle. Issue #118 separately owns reproducible PostgreSQL image dependency inputs. The licensing/IP authority makes Apache-2.0 metadata, project provenance, NOTICE, dependency/SBOM verification, and repository-vs-external legal evidence boundaries explicit. The live commercial gap queue is no longer hidden in issue bodies: #101, ACTIVE-PR #104/#105/#106/#114/#119, and Issues #98/#99/#100/#102/#103/#108/#109/#112/#113/#115/#116/#117/#118/#120 are classified here and their stable product/technical meanings are owned by the canonical graph. This is a documentation sufficiency statement, not a claim that all ACTIVE-PR capabilities are implemented, that every third-party obligation has been independently cleared for a future release/transaction, or that the product is release-ready.

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
12. **Privacy controls do not create host authorization.** Package-side redaction, bounded telemetry, selective-disclosure logging defaults, or future tenant RLS cannot substitute for host-selected purpose, identity, authorization, retention, erasure, backup, or residency policy.
13. **Source merge does not create operational closure.** Runtime-sensitive changes require fresh capability-specific protected-main acceptance evidence under ADR-0005 before incident/release closure where applicable.
14. **Scheduler failure is not repository failure.** A generic scheduled-task failure, silent completion, or empty user-visible output remains a control-plane incident until independently classified. Preserve one authoritative enabled scheduler, do not create a duplicate scheduler reflexively, compact prompt/control state instead of accumulating an unbounded incident transcript, treat user redirection as a queue re-evaluation trigger, resume a material safe repository action in the same invocation when one exists, and apply the normal double exit sweep before termination. Prompt repair alone is not recovery.
15. **Live exception objects are not audit records.** A constructor-time shallow snapshot may prevent outer caller-alias drift while leaving direct and nested mutation possible. Do not promote ACTIVE-PR #105 to immutable, append-only, cryptographic, or durable evidence semantics.
16. **Prompt source is not scheduler state.** `docs/automation/HOURLY_WRITER_PROMPT.md` is the compact hourly writer prompt authority for content and size, but scheduler enabled/cadence/run state must be refetched from the external control plane.
17. **Operation span status must preserve confidentiality and application authority.** ACTIVE-PR #106 may mark propagated failures Error only without a description or automatic exception recording; successful operations retain status Unset, and ordinary telemetry status construction/mutation failures must not replace the application result.
18. **Persistent-log privacy is not absence of live query text.** ACTIVE-PR #119 disables persistent SQL/bind/query-stat copies by default but keeps `pg_stat_activity` query text as a bounded volatile privileged surface while `track_activities` is enabled; deployment access to that surface must remain purpose-bound and least-privilege.
19. **Container logging rotation is not retention.** PLANNED Issue #120 must preserve #119's content/privacy boundary while making container log routing storage-bounded; platform/file rotation does not by itself establish deletion, retention, export, residency, or legal-hold policy.

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