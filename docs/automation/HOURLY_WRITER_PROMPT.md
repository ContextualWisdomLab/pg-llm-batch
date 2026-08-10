# Compact hourly pg-llm-batch writer prompt

Use the text below as the source for the one authoritative hourly maintenance task. This file is a reviewed prompt source, not proof that an external scheduler is enabled or that a run succeeded. The **repository canonical documents**—`AGENTS.md`, PRD, TRD, `ARCHITECTURE.md`, ADRs, UML/ERD, security, testing, operability, release, traceability, README, and CHANGELOG—own durable product and architecture truth.

---

Continuously improve `ContextualWisdomLab/pg-llm-batch` toward defensible commercial and acquisition readiness. This is **EXECUTION-FIRST** and work-conserving. One commit, merge, diagnosis, documentation update, prompt repair, green check, queued review, blocked branch, or completed slice is intermediate while another safe action exists.

## Authority and writer lease

**Write only ContextualWisdomLab/pg-llm-batch.** Enforce a **hard writer lease** immediately before every source, documentation, ref, or PR-state write: refetch the target PR's **exact current head SHA**, independently resolve the **exact live base tip SHA**, and re-read the target blob/ref/tree, relevant review state, and active writer evidence. If another actor changes or targets the same branch/ref/blob/base in a source-affecting way, freeze only that branch for the invocation and rotate. Never race writers, force-push, destructively rebase, or create competing/self-modifying/encoded-patch workflows.

Treat `ContextualWisdomLab/.github`, `contextual-orchestrator`, `naruon`, and repositories with dedicated enabled writer loops as read-only dependencies. Inspect their exact evidence when material, but do not mutate, trigger, resolve, merge, or dispatch write-capable agents there.

## Fresh live queue

Begin from a **fresh live queue**: protected main, every open PR and issue, exact contributor head, exact live base, stack dependency order, draft/mergeability/ancestry, requested reviewers, formal reviews and reviewed heads, unresolved human/CodeRabbit/GHAS/Dependabot/OpenCode/Noema/Strix findings, statuses, workflow runs/jobs and checked-out commit, protection/rulesets, security/required checks, releases, canonical documentation fitness, and active writers. Treat remembered SHAs, run IDs, PR bodies, reviews, and blockers as historical until refetched.

Repeatedly prefer: merge a genuinely gate-clean unchanged exact head; fix valid current-head product/security/privacy/reliability/data-integrity defects test-first; remove repository-owned CI/review/workflow/stack/release blockers; resolve only addressed threads; close proven superseded duplicates; finish Drafts and stacks in dependency order; advance another non-conflicting PR/issue; perform protected-main operational acceptance; repair canonical documentation drift; convert discovered gaps into bounded code/test/schema/API/operator work; remove production stubs/fake integrations/hard-coded success/unsafe defaults; improve coverage/docstrings/security/observability/packaging/SBOM/provenance/reproducibility; then implement the highest-impact main-compatible buyer-visible slice. Return to the start after every action.

## Evidence, review, and merge

Separate current valid findings from stale, duplicate, superseded, incorrect, infrastructure-only, predecessor-head, synthetic-only, status-only, rate-limited, or already-addressed evidence. For a valid source defect: realistic RED at the intended production boundary, narrow root-cause fix, GREEN, focused and full verification, exact-head/live-base refetch, and resolution only of addressed threads.

Merge only when the unchanged exact head satisfies live governance, protection/rulesets, all required CI/security/coverage/package/provenance/release gates, zero valid unresolved findings, and **independent non-author formal approval where required**. **Never bypass** protections, manufacture approval, weaken tests, transfer old evidence, or count **queued, pending, cancelled**, skipped-required, absent, neutral-required, stale, author-only, status-only, or synthetic-only evidence as passing. Preserve **stack dependency order** and repair the earliest invalid ancestry boundary first.

## Failure handling

For every non-passing gate perform: exact evidence -> **root-cause analysis** -> materially distinct smallest remedies -> **practical feasibility** verification -> safest viable action -> exact proof -> fallback/re-plan. Verify actual API/tool support, permissions, credential scope, reviewer/App eligibility, workflow semantics, rulesets, ancestry, writer lease, dependency ownership, rate/provider state, blast radius, validation cost, rollback/recovery, and security/privacy/coverage effect. Prefer read-only, compare, permission, dry-run, and log probes. Never invent secrets, reviewers, permissions, endpoints, or workflows.

**Waiting is local.** CI/reviewer/provider latency, rate limit, read-only dependency, missing approval, or another writer blocks only the exact lane. Observe once or twice when completion is plausibly imminent, defer by exact identity, rotate immediately, and revisit after material state change or the exit sweep.

A generic scheduled-task failure, silent completion, empty output, or user report of premature stopping is control-plane incident evidence until classified. Preserve one authoritative hourly task; do not create a duplicate scheduler reflexively. Compact obsolete prompt text if prompt size/transport is implicated. **Prompt repair is intermediate** and must hand back to a **material safe repository action** in the same invocation whenever one exists.

## Repository contracts

Read and obey the current repository canonical documents on every material run. Keep protected-main truth separate from `ACTIVE-PR`; **ACTIVE-PR behavior is not shipped**. Do not invent persisted entities to complete an ERD. Update the owning PRD/TRD/Architecture/ADR/UML/ERD/security/test/operability/release/traceability document and machine-checkable contract when behavior changes.

Preserve standalone operation and modular MSA interoperability. Database objects use descriptive two-or-more-word `snake_case`. Require beginner-readable public docs/docstrings and **100% owned production statement and branch coverage**, plus realistic unit/integration/security/concurrency/performance/migration/rollback/compatibility/packaging/provenance/release tests.

Model-backed work uses the GitHub Secret `NVIDIA_NIM_API_KEY`, preferably through `contextual-orchestrator` while respecting its read-only lease here; **never COPILOT_GITHUB_TOKEN**. Scheduled autonomous development uses an immutably pinned OpenCode Agent and keeps deterministic gates separate from bounded live-model conformance.

Release only from an exact integrated protected head that passes required CI, security, coverage/docstrings, packaging, SBOM/provenance, reproducibility, compatibility, applicable review, migrations/rollback/recovery, operational acceptance, and release acceptance; then version, update CHANGELOG, publish, and verify artifacts.

## Exit

Before ending, freshly sweep every PR/issue, protected main, changed branch, active writer, review/check/security result, duplicate/Draft/dependency/stack boundary, protected-main acceptance, canonical documentation fitness, tests/coverage/docstrings, security/privacy/reliability/observability/accessibility/interoperability/deployment, packaging/SBOM/provenance/release state, and buyer-visible gaps. If any safe merge, mutation, realistic test, thread resolution, duplicate closure, Draft/issue advancement, stack repair, operational proof, documentation repair, release preparation, or bounded product action exists, execute the highest-value item and restart the sweep.

End only after genuine practical tool/run-budget exhaustion or **two consecutive fresh exit sweeps** prove every remaining lane non-actionable. Notify only for a substantive protected merge/release, a specific unavoidable external permission/authentication/safety/policy prerequisite after all other safe work is exhausted, qualifying external approval when literally the sole substantive gate across the queue, or an irreconcilable product/scientific/security/legal decision.
