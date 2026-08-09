# ADR-0001: Work-conserving autonomous maintenance

- **Status:** ACTIVE-PR
- **Decision owner:** pg-llm-batch repository governance
- **Scope:** autonomous commercial-readiness and PR-maintenance execution

## Context

Hourly autonomous maintenance repeatedly encountered a control failure: an invocation would complete one useful repair, reach one queued check, discover one blocked PR, update a prompt/documentation artifact, or produce one successful merge and then terminate even though another safe pg-llm-batch action remained. That behavior wastes the finite invocation and turns the schedule into an artificial one-action throttle.

The repository also contains independent PRs, stacked PRs, local defects, documentation gaps and product work. Waiting on one lane is therefore not equivalent to waiting on the repository.

## Drivers

- maximize validated repository progress per invocation;
- avoid polling latency when another branch/issue is executable;
- preserve dependency order and branch-local writer safety;
- ensure RCA, documentation and prompt work hand off to implementation rather than becoming reports;
- keep user-visible narration from replacing repository work.

## Alternatives considered

### A. One target per scheduled invocation

Simple, but leaves large amounts of safe work idle and magnifies reviewer/provider latency. Rejected.

### B. Continue only until the first mutation succeeds

Better than diagnosis-only runs, but still stops on commits, merges, documentation or queued CI while other safe lanes remain. Rejected.

### C. Work-conserving queue with branch-local deferral

Continuously select the highest-value safe action, defer only the blocked transition, rotate to another lane, and stop only after budget exhaustion or a fresh double exit sweep proves there is no executable work. **Chosen.**

## Decision

Autonomous maintenance is **work-conserving**.

1. Maintain a live queue covering mergeable PRs, current-head defects, repository-owned blockers, addressed review threads, superseded duplicates, Draft/stack progression, accepted issues, protected-main acceptance, canonical documentation, quality/release evidence and bounded buyer-visible work.
2. After **every** mutation, proof, merge, closure, defer decision, prompt update or documentation change, select the next safe action in the same invocation.
3. A queued/pending check, reviewer/provider latency, missing independent approval, rate limit, read-only dependency or branch writer conflict blocks only that exact action/branch.
4. “One bounded slice” limits conflicting in-flight work; it does not mean one slice per invocation.
5. A focused user request chooses the first lane; after it becomes waiting or complete, the full queue resumes.
6. Prompt changes, plans, documentation audits, PR creation and CI dispatch are intermediate handoffs, not completion.
7. Routine progress narration is not counted as repository progress.
8. Before termination perform a **double exit sweep** from fresh state. If either sweep finds a safe action, execute it and sweep again.

This is the repository's **no-early-stop** contract.

## Branch rotation

When one branch is waiting or branch-frozen, preserve its exact identity in the internal deferred set and rotate to another non-conflicting branch or main-compatible task. Do not poll the same unchanged CI/review/provider for the remainder of the invocation. Revisit after a material state change, another substantive action, or the final sweep.

## Consequences

### Positive

- higher useful throughput without weakening merge gates;
- central/dependency outages have a smaller blast radius;
- documentation and governance gaps turn into repository state rather than status prose;
- existing open work is drained before speculative backlog grows.

### Negative

- each invocation must maintain a broader live state model;
- exact-head/base identity must be refreshed more often;
- branch-local conflicts require explicit defer bookkeeping;
- a finite invocation can end with several partially waiting lanes, but only after useful executable work is exhausted.

## Failure and recovery

If an invocation terminates after a single intermediate result while another safe lane demonstrably existed, treat the termination itself as a control incident. Identify the missed exit condition, repair this prompt/ADR/automation contract when necessary, and resume repository work. Do not create a duplicate autonomous writer as the remedy.

## Security and governance impact

Work conservation never authorizes bypassing protection, manufacturing approval, weakening tests, force-pushing, racing another writer, using invented credentials, or treating pending/stale/synthetic evidence as success. Safety and repository policy outrank throughput.

## Acceptance evidence

A compliant run demonstrates multiple sequential non-conflicting actions when available, branch-local deferral around waits, prompt/documentation-to-repository handoff, and a final double exit sweep. The acceptance signal is repository state transition, not a textual claim that the loop is active.

## Rollback

Rollback would mean returning to a one-target/one-action scheduler. That is allowed only through a superseding ADR with evidence that broader work conservation is unsafe or operationally worse. Merely encountering a long run is not sufficient justification.

## Supersession

A future ADR may replace this policy only if it explicitly preserves or intentionally changes no-early-stop, branch rotation, prompt/documentation handoff and double-exit semantics.
