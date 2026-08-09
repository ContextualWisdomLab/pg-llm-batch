# Requirements, decisions, and evidence traceability

## Purpose

This matrix makes product and governance claims auditable without relying on chat history. Status must be read together with the exact source branch: **IMPLEMENTED-ON-PROTECTED-MAIN** means protected `main`; **ACTIVE-PR** means the capability exists only on an open implementation/documentation branch.

## Core product traceability

| Requirement / decision | Maturity | Source / schema | Tests / evidence | Owning documentation |
| --- | --- | --- | --- | --- |
| PostgreSQL-backed configuration and secrets | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/schema.sql`, config/secret store modules | repository CI + config/secret tests | PRD, TRD, `SECURITY.md`, API_CONTRACT |
| Token-aware deterministic batch preparation | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/orchestrator.py`, `pg_llm_batch/schema.sql` | orchestrator/token/schema tests | PRD, TRD, ARCHITECTURE |
| OpenAI-compatible bounded Files/Batches client | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/batch_api_client.py` | HTTP control/download/retry/security tests | TRD, THREAT_MODEL, API_CONTRACT |
| Durable remote lifecycle observations | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/durable_client.py`, `llm_remote_batch_jobs` in `pg_llm_batch/schema.sql` | lifecycle/concurrency/schema tests | ARCHITECTURE, ERD, OPERABILITY, API_CONTRACT |
| Readiness contract | IMPLEMENTED-ON-PROTECTED-MAIN | `pg_llm_batch/health.py`, `pg_llm_batch/schema.sql` | health tests + `.github/workflows/ci.yml` | OPERABILITY, UML, API_CONTRACT |
| Public Python/CLI/schema compatibility authority | ACTIVE-PR #93 | protected-main `pg_llm_batch/__init__.py`, `pg_llm_batch/cli.py`, `pg_llm_batch/schema.sql` mirrored into canonical compatibility policy | documentation fitness contract + live source reconciliation | `docs/product/API_CONTRACT.md` |
| Release/rollback/provenance acceptance authority | ACTIVE-PR #93 | package/workflow/migration/runtime evidence classes | documentation fitness contract + exact integrated-head release gates | `docs/RELEASE_ACCEPTANCE.md` |
| Tenant-qualified lifecycle + forced RLS | ACTIVE-PR #53 | PR #53 lifecycle/schema changes | exact-head branch CI/security + live PostgreSQL evidence | THREAT_MODEL, ERD overlay |
| Descriptor-pinned reproducible release evidence | ACTIVE-PR #57 | PR #57 release helpers/workflows | branch Release Acceptance/reproducibility tests | TEST_STRATEGY, OPERABILITY, RELEASE_ACCEPTANCE |
| Incremental bounded result records | ACTIVE-PR #58 | PR #58 streaming client surfaces | branch CI/release acceptance | TRD, UML |
| Prefix-bound resumable checkpoints | ACTIVE-PR #59 | PR #59 checkpoint contracts | checkpoint integrity/resume tests | TRD, UML |
| Durable checkpoint CAS storage | ACTIVE-PR #60 | `llm_result_stream_checkpoints` migration in PR #60 | live PostgreSQL/RLS/CAS/rollback tests | ERD overlay, THREAT_MODEL |
| Checkpoint observability replacement | ACTIVE-PR #92 | PR #92 checkpoint telemetry | fresh replacement exact-head evidence required | UML, TEST_STRATEGY |
| Append-only checkpoint audit replacement | ACTIVE-PR #94 | `llm_result_checkpoint_audit_events` migration and audit module | fresh replacement CI/live PostgreSQL evidence required | ERD overlay, THREAT_MODEL |
| Atomic checkpoint migration operator replacement | ACTIVE-PR #95 | migration operator, CLI/API, CI and live PostgreSQL contracts on #95 | fresh exact-head/exact-base rollback/concurrency evidence required | ADR index, OPERABILITY |
| Bounded stable checkpoint-audit pagination replacement | ACTIVE-PR #96 | pagination/cursor/public API composition on #96 | fresh exact-head/live PostgreSQL pagination evidence required | ADR index, UML/ERD overlay |
| Snapshot-manifest assurance | PARTIAL | stale PR #84 contains unique implementation on closed #83 ancestry; a live successor branch is being rebuilt from #96 | historical evidence does not transfer; current successor exact ancestry and fresh gates are required | ADR index; checkpoint-audit doctoring |
| Exact source-head CI evidence | ACTIVE-PR #88 | `.github/workflows/ci.yml` on #88 | exact contributor head checkout/verification tests | ADR-0002, TEST_STRATEGY |
| Canonical product documentation authority | ACTIVE-PR #93 | this documentation graph | `tests/test_documentation_fitness_contract.py` + normal CI | DOCUMENTATION_FITNESS |
| Operator CLI batch cancellation | PLANNED | issue #90; existing `BatchAPIClient.cancel_batch()` primitive | implementation blocked until overlapping CLI/resource ownership work settles | PRD/TRD/API contract follow-up |

## Evidence-identity traceability

The repository treats these as separate authorities:

- **exact contributor head** — immutable source revision being reviewed/tested;
- **PR base snapshot** — base metadata captured for a pull request event/state and not assumed to equal the current branch tip;
- **live base** — independently resolved current tip of the target base ref used for current compatibility/ancestry decisions;
- **synthetic merge revision** — GitHub-generated integration candidate, useful only when the workflow contract explicitly calls for it;
- **check/status evidence** — execution result for the commit actually checked out;
- **semantic review evidence** — review of source semantics, not proof that infrastructure or tests passed;
- **independent approval** — qualifying non-author formal review where live policy/governance requires it.

A green check cannot replace independent approval, and an infrastructure failure cannot be synthesized into a source-code finding without independent source evidence.

## Automation/governance traceability

| Decision | Repository authority | Acceptance / recovery |
| --- | --- | --- |
| Work-conserving no-early-stop maintenance | `docs/automation/ADR-0001-work-conserving-maintenance.md` | after every action/defer, select next safe lane; double exit sweep before termination |
| Branch-local writer lease and read-only dependencies | `docs/automation/ADR-0002-evidence-identity-and-writer-lease.md` | pre-write exact-ref re-read; freeze only conflicting branch; no force push/race |
| Exact source vs live-base evidence separation | ADR-0002 + ACTIVE-PR #88 | current source head and independently resolved live base must be separately recorded |
| Central `.github` ownership of reusable review/bootstrap defects | ADR-0002 + repository automation contract | pg-llm-batch treats leased central fixes read-only and does not weaken leaf product code |
| Prompt/documentation updates are intermediate | ADR-0001 | control-plane change must hand back to executable repository work when safe |
| Public compatibility/versioning authority | `docs/product/API_CONTRACT.md` | shipped, ACTIVE-PR, deprecated, and breaking behavior must be explicit and testable |
| Release/publish authority | `docs/RELEASE_ACCEPTANCE.md` | exact integrated protected head + independent applicable gates + post-publication verification |

## Stack-replacement traceability

The checkpoint chain is currently linearized through replacements rather than destructive rewrites:

- #78 -> #92;
- #79 -> #94;
- #80 -> #95;
- #83 -> #96;
- #84 remains the stale snapshot-manifest implementation; a live successor branch currently descends directly from the exact #96 head and must complete its full unique delta before #84 can be closed as SUPERSEDED.

No check, review, approval, or historical base evidence transfers across a replacement. The successor must prove exact ancestry, preserved unique behavior, and fresh exact-head/exact-base evidence.

## Security, operability, and release traceability

- Destination, resource-ID, response-bound and retry controls: `pg_llm_batch/batch_api_client.py` -> HTTP/security tests -> `docs/THREAT_MODEL.md`.
- Durable state and schema: `pg_llm_batch/schema.sql` -> schema/lifecycle integration tests -> `docs/architecture/ERD.md`.
- Runtime readiness: `pg_llm_batch/health.py` + database health helper -> health tests -> `docs/OPERABILITY.md`.
- Disclosure policy: `SECURITY.md` -> vulnerability-reporting process; threat-model controls do not replace disclosure policy.
- Exact-source workflow governance: `.github/workflows/ci.yml` -> workflow contract tests -> ACTIVE-PR #88 + ADR-0002.
- Public compatibility: `pg_llm_batch/__init__.py` + `pg_llm_batch/cli.py` + schema -> `docs/product/API_CONTRACT.md`.
- Release decision: CI/security/package/migration/runtime/review/artifact evidence -> `docs/RELEASE_ACCEPTANCE.md`.

## Documentation maintenance

When source/schema/workflow behavior changes, update the owning row and status in this file in the same bounded workstream or the single canonical documentation branch. If an ACTIVE-PR merges, replace its status with IMPLEMENTED-ON-PROTECTED-MAIN only after protected-main source is freshly verified. If it is closed/superseded, record the successor or remove the stale target claim.

Dated SHAs/run IDs belong in PR bodies or incident evidence, not this timeless matrix, except where a historical incident is necessary to explain a durable decision.
