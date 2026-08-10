# Requirements, decisions, and evidence traceability

## Purpose

This matrix makes product and governance claims auditable without relying on chat history. Status must be read together with the exact source branch: **IMPLEMENTED-ON-PROTECTED-MAIN** means protected `main`; **ACTIVE-PR** means the capability exists only on an open implementation/documentation branch.

Evidence listed for an ACTIVE-PR belongs only to that implementation PR's exact source/base relation at the time it was observed. It is not evidence for this documentation branch, a later head, a synthetic merge revision, or protected `main`. Any head/base movement requires the affected gates to be reacquired before integration.

## Core product traceability

| Requirement / decision | Maturity | Source / schema | Tests / evidence | Owning documentation |
| --- | --- | --- | --- | --- |
| PostgreSQL-backed configuration and secrets | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/schema.sql`, config/secret store modules | repository CI + config/secret tests | PRD, TRD, `SECURITY.md`, API_CONTRACT |
| Token-aware deterministic batch preparation | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/orchestrator.py`, `pg_llm_batch/schema.sql` | orchestrator/token/schema tests | PRD, TRD, ARCHITECTURE |
| OpenAI-compatible bounded Files/Batches client | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/batch_api_client.py` | HTTP control/download/retry/security tests | TRD, THREAT_MODEL, API_CONTRACT |
| Durable remote lifecycle observations | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/durable_client.py`, `llm_remote_batch_jobs` in `pg_llm_batch/schema.sql` | lifecycle/concurrency/schema tests | ARCHITECTURE, ERD, OPERABILITY, API_CONTRACT |
| Readiness contract | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/health.py`, `pg_llm_batch/schema.sql` | health tests + `.github/workflows/ci.yml` | OPERABILITY, UML, API_CONTRACT |
| Apache-2.0 outbound license and repository provenance artifacts | IMPLEMENTED-ON-PROTECTED-MAIN | `pyproject.toml`, `LICENSE`, `NOTICE` | package metadata/license-file checks at release; repository statements do not replace external title/legal evidence | `docs/LICENSING_AND_IP.md`, RELEASE_ACCEPTANCE |
| Data-governance/privacy authority | ACTIVE-PR #93 | protected-main schema/content-bearing fields, provider client, secret/config stores, observability, health/diagnostic surfaces | `tests/test_data_governance_documentation_contract.py` + existing security/telemetry/provider-bound tests; host authorization/retention/residency remain deployment evidence rather than package claims | `docs/DATA_GOVERNANCE.md`, DOCUMENTATION_FITNESS, RELEASE_ACCEPTANCE |
| Licensing/IP/third-party acquisition-diligence authority | ACTIVE-PR #93 | protected-main license/provenance artifacts mirrored into a canonical diligence boundary | `tests/test_acquisition_licensing_contract.py` + exact release dependency/SBOM/license verification; unknown obligations fail closed | `docs/LICENSING_AND_IP.md`, DOCUMENTATION_FITNESS |
| Public Python/CLI/schema compatibility authority | ACTIVE-PR #93 | protected-main `pg_llm_batch/__init__.py`, `pg_llm_batch/cli.py`, `pg_llm_batch/schema.sql` mirrored into canonical compatibility policy | documentation fitness contract + live source reconciliation; current #93 gates remain head-specific | `docs/product/API_CONTRACT.md` |
| Release/rollback/provenance acceptance authority | ACTIVE-PR #93 | package/workflow/migration/runtime evidence classes | documentation fitness contract + exact integrated-head release gates; documentation-branch checks do not substitute for release acceptance | `docs/RELEASE_ACCEPTANCE.md` |
| Tenant-qualified lifecycle + forced RLS | ACTIVE-PR #53 | PR #53 lifecycle/schema changes | branch CI/security/live PostgreSQL evidence belongs only to #53's unchanged head/base; final exact-head review and protected-main gates required | THREAT_MODEL, ERD overlay, DATA_GOVERNANCE |
| Descriptor-pinned reproducible release evidence | ACTIVE-PR #57 | PR #57 release helpers/workflows | staged reproducibility/Release Acceptance evidence belongs only to #57's verified head/base; final protected-main gates required | TEST_STRATEGY, OPERABILITY, RELEASE_ACCEPTANCE |
| Incremental bounded result records | ACTIVE-PR #58 | PR #58 streaming client surfaces | staged branch CI/Release Acceptance evidence is #58-specific; final integrated gates required | TRD, UML, DATA_GOVERNANCE |
| Prefix-bound resumable checkpoints | ACTIVE-PR #59 | PR #59 checkpoint contracts | checkpoint integrity/resume evidence is #59-specific; final integrated gates required | TRD, UML |
| Durable checkpoint CAS storage | ACTIVE-PR #60 | `llm_result_stream_checkpoints` migration in PR #60 | staged live PostgreSQL/RLS/CAS/rollback evidence is #60-specific; final integrated gates required | ERD overlay, THREAT_MODEL, DATA_GOVERNANCE |
| Checkpoint observability replacement | ACTIVE-PR #92 | PR #92 checkpoint telemetry | staged #92 exact-head CI/Release Acceptance were observed successful on its recorded replacement relation; no evidence transfers after head/base change | UML, TEST_STRATEGY, DATA_GOVERNANCE |
| Append-only checkpoint audit replacement | ACTIVE-PR #94 | `llm_result_checkpoint_audit_events` migration and audit module | staged #94 exact-head CI/Release Acceptance were observed successful on its recorded replacement relation; final protected-main/live PostgreSQL gates remain required | ERD overlay, THREAT_MODEL, DATA_GOVERNANCE |
| Atomic checkpoint migration operator replacement | ACTIVE-PR #95 | migration operator, CLI/API, CI and live PostgreSQL contracts on #95 | staged #95 exact-head CI/Release Acceptance were observed successful on its recorded replacement relation; final rollback/concurrency/protected-main gates remain required | ADR index, OPERABILITY |
| Bounded stable checkpoint-audit pagination replacement | ACTIVE-PR #96 | pagination/cursor/public API composition on #96 | staged #96 exact-head CI/Release Acceptance were observed successful on its recorded replacement relation; final protected-main/live PostgreSQL gates remain required | ADR index, UML/ERD overlay |
| Snapshot-manifest assurance replacement | ACTIVE-PR #97 | snapshot-manifest implementation composed on exact #96 pagination predecessor | staged #97 CI/Release Acceptance evidence belongs only to its recorded replacement relation; #84 evidence does not transfer and final integrated gates remain required | ADR index; checkpoint-audit doctoring |
| Repository maintenance credential/writer hardening | ACTIVE-PR #69 | hourly-maintenance workflow/caller contract | branch checks are staged only; central `.github` prerequisite must reach protected main before final pin/evidence | ADR index, automation governance |
| Readiness disclosure, resource, and listener hardening | ACTIVE-PR #70 | health server/CLI/container contracts | branch CI/security/SAST evidence is #70-specific; #88 integration and final exact-source gates remain required | THREAT_MODEL, OPERABILITY, ADR index, DATA_GOVERNANCE |
| Bounded GET retry/TLS/response-handoff and provider-error confidentiality | ACTIVE-PR #71 | `pg_llm_batch/batch_api_client.py` retry, transport-classification, HTTP-error translation, and cancellation-rejection hardening | #71 branch confidentiality REDs prove protected-main-era error paths could retain provider-controlled content; current #71 CI/security/SAST evidence remains branch-specific and final exact-source/review gates remain required | TRD, THREAT_MODEL, ADR index, DATA_GOVERNANCE, provider-error doctoring |
| Provider secret input outside process argv | ACTIVE-PR #85 | CLI secret-input contract | protected main still accepts positional secret input; #85 branch evidence must not be presented as shipped behavior | THREAT_MODEL, API_CONTRACT, README active-PR note, DATA_GOVERNANCE |
| Typed configuration canonicalization and mutable-cache isolation | ACTIVE-PR #86 | config deserialization/write/cache contracts | branch CI/security/SAST evidence is #86-specific; final integration must reconcile overlap with #87/#89 | TRD, THREAT_MODEL, ADR index |
| PostgreSQL operation/store connection ownership | ACTIVE-PR #87 | orchestrator/CLI/config/secret/token owner lifetimes | branch CI/security/SAST evidence is #87-specific; final integration must reconcile overlap with #86/#89 | OPERABILITY, THREAT_MODEL, ADR index |
| Explicit bootstrap source precedence | ACTIVE-PR #89 | DSN/Fernet bootstrap resolvers | branch CI/security/SAST evidence is #89-specific; final integration must reconcile overlapping config authority | TRD, THREAT_MODEL, ADR index |
| Loopback-only standalone Compose publication | ACTIVE-PR #91 | Compose port mappings + documentation contract | branch CI/security/SAST evidence is #91-specific; current automated review/independent policy gates remain separate | THREAT_MODEL, OPERABILITY, ADR index |
| Exact source-head CI evidence | ACTIVE-PR #88 | `.github/workflows/ci.yml` on #88 | repository CI/security/SAST passed the recorded #88 head, but central OpenCode coverage-evidence remains an infrastructure blocker and no predecessor evidence substitutes | ADR-0002, TEST_STRATEGY |
| Canonical product documentation authority | ACTIVE-PR #93 | this documentation graph | documentation tests + current branch CI are required on each new #93 head; predecessor successes do not transfer | `docs/automation/ADR-0003-canonical-documentation-authority.md`, DOCUMENTATION_FITNESS |
| Legacy direct-SQL provider retrieval retirement | ACTIVE-PR #101 | `docker/postgres/init/03_cron_batch_retrieval.sql` cleanup + doctoring | #101 exact-head CI/security/SAST are branch-specific; historical logs are retained, exact legacy job is unscheduled, and provider HTTP must remain in the Python client authority | PRD, TRD, legacy retrieval doctoring |
| Public `BatchRequest` exact runtime typing and rejected-value confidentiality | ACTIVE-PR #104 | `pg_llm_batch/models.py` | focused type-boundary and confidentiality regressions plus #104 head-specific CI/security/SAST; final protected-main exact-source evidence remains required | API_CONTRACT, DOCUMENTATION_FITNESS |
| Structured error evidence snapshot | ACTIVE-PR #105 | `pg_llm_batch/exceptions.py` | focused caller-alias, absent-response, coverage, and doctoring regressions; the target is a constructor-time shallow snapshot, not immutable or durable audit evidence | API_CONTRACT, DATA_GOVERNANCE, `docs/doctoring/structured-error-evidence-integrity.md`, DOCUMENTATION_FITNESS |
| Operator CLI batch cancellation | PLANNED #90 | Issue #90; existing `BatchAPIClient.cancel_batch()` primitive | implementation intentionally blocked until overlapping #85/#87 CLI/resource ownership settles and #88 exact-source governance integrates | PRD/TRD/API contract follow-up |
| Strict provider progress and finite control JSON | PLANNED #98 | Issue #98; overlapping #71 provider-control parser surface | implement only after #71 settles or is superseded; malformed/non-finite control data must fail through bounded package diagnostics | PRD, TRD follow-up |
| Deployment-specific standalone PostgreSQL credential | PLANNED #99 | Issue #99; overlapping #91 Compose surface | remove shared default credential without weakening loopback-only publishing; prove arbitrary secret characters, restart, wrong-secret failure, and non-disclosure | PRD, TRD follow-up |
| Reproducible component-image OS dependencies | PLANNED #100 | Issue #100; overlapping #70 Dockerfile surface | replace mutable upgrade/unversioned resolution with machine-checkable package-source/version/snapshot evidence bound into SBOM/provenance | PRD, TRD, release follow-up |
| Automatic provider reconciliation through validated Python boundary | PLANNED #102 | Issue #102; durable lifecycle identity + provider client | restore bounded scheduled/worker reconciliation only after #101 and overlapping lifecycle/resource surfaces settle; no direct SQL HTTP and no distributed exactly-once claim | PRD, TRD, operability follow-up |
| Legacy PostgreSQL extension retirement | PLANNED #103 | Issue #103; post-#101 existing-volume extension/runtime cleanup | after #101 reaches protected main, prove clean fresh database and upgraded legacy-volume migration, dependency-safe `pg_cron`/`pgsql-http` removal, rollback/recovery, SBOM/provenance, and Release Acceptance; never use `DROP EXTENSION ... CASCADE` | `docs/adr/legacy-postgresql-extension-retirement.md`, PRD, TRD, operability follow-up |

## Evidence-identity traceability

The repository treats these as separate authorities:

- **exact contributor head** — immutable source revision being reviewed/tested;
- **PR base snapshot** — base metadata captured for a pull request event/state and not assumed to equal the current branch tip;
- **live base** — independently resolved current tip of the target base ref used for current compatibility/ancestry decisions;
- **synthetic merge revision** — GitHub-generated integration candidate, useful only when the workflow contract explicitly calls for it;
- **check/status evidence** — execution result for the commit actually checked out;
- **semantic review evidence** — review of source semantics, not proof that infrastructure or tests passed;
- **independent approval** — qualifying non-author formal review where live policy/governance requires it; and
- **code-owner review hold** — protected `AGENTS.md` records code-owner review gates disabled and **on hold** for the current single-maintainer state; it is not a universal approval requirement and must remain separate from other review evidence **where required**.

A green check cannot replace independent approval where policy requires it, and an infrastructure failure cannot be synthesized into a source-code finding without independent source evidence. The current code-owner hold likewise cannot be silently re-enabled by a PR body, automation prompt, or documentation assumption.

## Automation/governance traceability

| Decision | Repository authority | Acceptance / recovery |
| --- | --- | --- |
| Work-conserving no-early-stop maintenance | `docs/automation/ADR-0001-work-conserving-maintenance.md` | after every action/defer, select next safe lane; double exit sweep before termination |
| Branch-local writer lease and read-only dependencies | `docs/automation/ADR-0002-evidence-identity-and-writer-lease.md` | pre-write exact-ref re-read; freeze only conflicting branch; no force push/race |
| Exact source vs live-base evidence separation | ADR-0002 + ACTIVE-PR #88 | current source head and independently resolved live base must be separately recorded |
| Semantic review vs infrastructure/policy evidence separation | `docs/automation/ADR-0004-review-evidence-separation.md` | infrastructure-only failure remains a blocker but must not become a synthetic source finding; unavailable semantic review records ABSTAIN/UNAVAILABLE and is rerun after the owning prerequisite materially changes |
| Code-owner review hold | protected `AGENTS.md` + ADR-0004 + `docs/RELEASE_ACCEPTANCE.md` | code-owner review gates remain disabled and on hold for the single-maintainer state; do not re-enable them until authoritative governance changes; evaluate semantic/independent approval separately where required by live policy |
| Protected-main operational acceptance | `docs/automation/ADR-0005-protected-main-operational-acceptance.md` | source merge is intermediate; collect fresh capability-specific protected-main evidence before incident/release closure where applicable, while read-only dependency failure blocks only that acceptance lane |
| Scheduler failure recovery | `docs/automation/ADR-0006-scheduler-failure-recovery.md` | classify generic scheduler/control-plane symptoms, silent completion, and empty user-visible output separately from repository failure; user redirection must resume a material safe repository action when one exists; prompt repair alone is not recovery; retain one authoritative enabled hourly task and finish through the normal double exit sweep |
| Central `.github` ownership of reusable review/bootstrap defects | ADR-0002 + repository automation contract | pg-llm-batch treats leased central fixes read-only and does not weaken leaf product code |
| Prompt/documentation updates are intermediate | ADR-0001 + ADR-0006 | control-plane change must hand back to a material safe repository action when safe; silent completion is not acceptance |
| Canonical documentation authority and maturity discipline | `docs/automation/ADR-0003-canonical-documentation-authority.md` | protected-main and ACTIVE-PR truth remain separate; machine-checkable fitness catches drift |
| Data-governance/privacy authority | `docs/DATA_GOVERNANCE.md` | classify package-owned fields/signals; preserve purpose-bound utility; host retains authorization, retention, erasure, backup, and residency authority unless an accepted implementation explicitly moves that boundary |
| Public compatibility/versioning authority | `docs/product/API_CONTRACT.md` | shipped, ACTIVE-PR, deprecated, and breaking behavior must be explicit and testable |
| Licensing/IP acquisition authority | `docs/LICENSING_AND_IP.md` | exact package metadata + LICENSE/NOTICE consistency + dependency/SBOM/upstream-license verification; unresolved ownership/license evidence fails closed and repository declarations do not replace legal review |
| Release/publish authority | `docs/RELEASE_ACCEPTANCE.md` | exact integrated protected head + independent applicable gates + post-publication verification |

## Stack-replacement traceability

The checkpoint chain is currently linearized through replacements rather than destructive rewrites:

- #78 -> #92;
- #79 -> #94;
- #80 -> #95;
- #83 -> #96;
- #84 -> #97.

`#84` is closed unmerged as SUPERSEDED by `#97`. No check, review, approval, or historical base evidence transfers across any replacement. Each successor must prove exact ancestry, preserved unique behavior, and fresh exact-head/exact-base evidence.

## Security, operability, and release traceability

- Destination, resource-ID, response-bound and retry controls: `pg_llm_batch/batch_api_client.py` -> HTTP/security tests -> `docs/THREAT_MODEL.md` and `docs/DATA_GOVERNANCE.md`.
- Provider-error confidentiality: ACTIVE-PR #71 -> provider-error confidentiality regressions and retry/error doctoring -> `docs/DATA_GOVERNANCE.md`; do not promote this overlay to protected-main evidence before integration.
- Structured error evidence snapshot: ACTIVE-PR #105 -> caller-alias/absence/coverage regressions and `docs/doctoring/structured-error-evidence-integrity.md` -> `docs/product/API_CONTRACT.md` + `docs/DATA_GOVERNANCE.md`; shallow constructor snapshots are not immutable audit records.
- Legacy direct-SQL provider retrieval: ACTIVE-PR #101 -> exact legacy job/function cleanup tests + doctoring -> PRD/TRD; decommissioning the unsafe SQL network authority is separate from the PLANNED #102 automatic-reconciliation replacement.
- Durable state and schema: `pg_llm_batch/schema.sql` -> schema/lifecycle integration tests -> `docs/architecture/ERD.md` and `docs/DATA_GOVERNANCE.md`.
- Runtime readiness: `pg_llm_batch/health.py` + database health helper -> health tests -> `docs/OPERABILITY.md` and public-data limits in `docs/DATA_GOVERNANCE.md`.
- Autonomous scheduler failure recovery: task-state evidence + live GitHub evidence -> `docs/automation/ADR-0006-scheduler-failure-recovery.md` + `docs/OPERABILITY.md`; silent completion or prompt repair alone is not recovery, and user redirection resumes a material safe repository action when one exists.
- Review-governance truth: protected `AGENTS.md` + ADR-0004 + live branch/ruleset policy -> `docs/RELEASE_ACCEPTANCE.md`; the code-owner gate remains on hold while other review/approval is evaluated only where required.
- Telemetry privacy: `pg_llm_batch/observability.py` + observability tests -> `docs/doctoring/opentelemetry-operations.md` -> `docs/DATA_GOVERNANCE.md`.
- Disclosure policy: `SECURITY.md` -> vulnerability-reporting process; threat-model/data-governance controls do not replace disclosure policy.
- Exact-source workflow governance: `.github/workflows/ci.yml` -> workflow contract tests -> ACTIVE-PR #88 + ADR-0002.
- Public compatibility: `pg_llm_batch/__init__.py` + `pg_llm_batch/cli.py` + schema -> `docs/product/API_CONTRACT.md`.
- Licensing/IP diligence: `pyproject.toml` + `LICENSE` + `NOTICE` + exact dependency/SBOM evidence -> `docs/LICENSING_AND_IP.md`.
- Release decision: CI/security/package/migration/runtime/review/artifact/licensing/data-governance evidence -> `docs/RELEASE_ACCEPTANCE.md`.

## Documentation maintenance

When source/schema/workflow behavior changes, update the owning row and status in this file in the same bounded workstream or the single canonical documentation branch. New persisted fields, logs, metrics, traces, provider disclosures, export surfaces, autonomous-maintenance failure modes, or review-governance changes must also be classified by their authoritative documentation family. If an ACTIVE-PR merges, replace its status with IMPLEMENTED-ON-PROTECTED-MAIN only after protected-main source is freshly verified. If it is closed/superseded, record the successor or remove the stale target claim.

Dated SHAs/run IDs belong in PR bodies or incident evidence, not this timeless matrix, except where a historical incident is necessary to explain a durable decision.
