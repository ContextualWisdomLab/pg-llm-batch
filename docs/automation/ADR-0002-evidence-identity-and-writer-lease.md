# ADR-0002: Evidence identity and writer lease

- **Status:** ACTIVE-PR
- **Scope:** pull-request evidence and repository write coordination

## Context

GitHub exposes multiple revisions and evidence channels: the exact contributor head, historical pull-request base metadata, the current live base ref, generated integration revisions, checks, workflow runs, review comments and formal review submissions. Stacked branches add a moving predecessor. These identities are related but not interchangeable.

Scheduled and interactive maintenance can also overlap. A repository therefore needs a simple coordination rule that prevents two actors from editing the same branch from stale state without unnecessarily blocking unrelated work.

## Alternatives

1. Treat PR metadata and any green status as current evidence. Rejected because base refs and source heads can move independently.
2. Rewrite a branch whenever a base changes. Rejected as the default because it invalidates evidence even when no integration change is required.
3. Keep evidence identities separate and use a branch-local writer lease. **Chosen.**

## Decision

The repository records and reasons about these authorities separately:

- **exact contributor head** — source revision being proposed;
- **PR base snapshot** — historical base SHA captured in PR/event metadata;
- **live base** — independently resolved current target-branch tip;
- **stack predecessor head** — exact current head of an immediate stacked base;
- **synthetic integration revision** — generated integration evidence, not a silent substitute for contributor-head evidence;
- **check/workflow evidence** — result for the commit actually exercised;
- **semantic review evidence** — review tied to the revision actually reviewed;
- **independent approval** — qualifying non-author formal approval when repository policy requires it.

An infrastructure or policy failure can block merge readiness without becoming a source-code finding. A semantic source finding likewise remains independent of infrastructure status.

### Writer lease

This maintenance loop writes only pg-llm-batch. A repository that has its own dedicated writer is a **read-only dependency** from this loop.

Before each pg-llm-batch write, refetch the target branch/head, intended live base, relevant target file/ref and PR/review state. If another write-capable actor changed or is actively changing the same branch in a source-affecting way, freeze only that branch for the invocation and rotate to another safe lane. Publish only from freshly revalidated state.

## Stacked PRs

A stacked head must descend from its current predecessor. Repair the earliest invalid boundary first. If a replacement is required, start from the exact current predecessor, preserve all unique work, reacquire checks/reviews on the replacement and then close the superseded PR with an explicit reason. Evidence from the predecessor PR does not transfer automatically.

## Consequences

This policy costs extra refetch/compare work and can require controlled replacement PRs, but it keeps source identity, integration compatibility, check evidence and review governance auditable. A conflict on one branch does not freeze unrelated pg-llm-batch work.

## Failure and recovery

If branch state changes between required reads, discard the stale assumption and re-plan that branch. If evidence identity is ambiguous, classify it as unproven rather than promoting it. If a read-only dependency is the failing owner, record the dependency and continue unrelated local work.

## Verification

Acceptance requires separate recording of exact contributor head and live base, current stacked-predecessor identity before reconciliation, commit-bound check evidence, formal independent approval where required, and branch-local deferral when another writer moves the target.

## Rollback and supersession

A superseding ADR must define an equally explicit source/base/check/review authority model and a coordination mechanism that prevents stale overlapping writes. Until then this decision remains the repository governance target.
