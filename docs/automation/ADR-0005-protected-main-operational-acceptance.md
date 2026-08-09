# ADR-0005: Protected-main operational acceptance

- Status: ACTIVE-PR
- **Scope:** post-merge operational, incident-closure, and release-readiness evidence

## Context

A pull-request check, semantic review, and successful source merge prove important but different things. They do not by themselves prove that the integrated revision behaves correctly from protected main under the repository's real scheduled, manual, deployment, database, credential, packaging, or provider-facing path. Treating merge as closure can therefore leave an incident or release decision supported only by pre-integration evidence.

The maintenance contract also requires work to continue after a merge rather than ending on a report. When a protected-main acceptance path depends on an organization-owned workflow or another repository with its own writer, that repository is a read-only dependency from this loop; its failure must be kept separate from a local product defect.

## Alternatives

1. **Treat passing PR checks plus source merge as operational closure.** Rejected because PR evidence can exercise a synthetic integration revision, predecessor base, or non-production execution path and cannot establish post-merge runtime behavior.
2. **Require ad hoc manual acceptance only immediately before a public release.** Rejected because incident closure and operational regressions need the same evidence discipline before release day, and ad hoc checks are difficult to reproduce or audit.
3. **Require bounded, capability-specific protected-main operational acceptance.** Chosen because it preserves evidence identity without demanding irrelevant end-to-end work for every change.

## Decision

A **source merge is an intermediate state**, not automatic operational closure.

For a change whose risk or acceptance contract includes runtime, deployment, migration, scheduler, provider, packaging, or other integrated behavior, the repository must:

1. independently resolve the exact current protected main revision after merge;
2. identify the smallest capability-specific operational acceptance path that exercises the changed boundary from that protected revision;
3. collect **fresh evidence** that records the protected source revision, the workflow/run or operator invocation, the commit actually exercised, material environment/version assumptions, and the observed outcome;
4. keep source/check/security/review evidence separate from protected-main runtime evidence rather than allowing one green signal to substitute for another;
5. treat queued, absent, skipped, stale, synthetic-only, predecessor-head, or failed operational evidence as unproven rather than successful;
6. if a **read-only dependency** blocks the acceptance path, record that dependency as the owning blocker, continue unrelated safe pg-llm-batch work, and rerun acceptance only after the prerequisite materially changes; and
7. require protected-main **operational acceptance** before declaring an incident operationally closed or a release/runtime-sensitive change ready where that evidence class is applicable.

Operational acceptance is capability-specific. A documentation-only change may need only documentation/source checks, while a migration change needs live PostgreSQL migration/rollback evidence, a health/deployment change needs protected-main startup/readiness evidence, and an automation change needs a protected-main scheduled or manual execution of the governed path. This ADR does not manufacture a universal end-to-end test for changes whose accepted risk model does not require one.

A clean integrated head must not be mutated merely to manufacture a new source SHA for an unavailable external reviewer or read-only dependency. Missing evidence is resolved by restoring the evidence path and rerunning it against the unchanged protected source when possible.

## Consequences

- A protected merge can be technically correct yet remain operationally unaccepted until the applicable post-merge proof exists.
- Incident closure and release readiness become more auditable because the exact integrated revision and runtime evidence are bound explicitly.
- Some changes incur an additional scheduled/manual acceptance run, but unrelated work continues while that lane waits.
- The repository avoids overclaiming a green PR, synthetic merge ref, or infrastructure status as production-runtime proof.

## Failure and recovery

If protected-main acceptance fails, first identify the exact failing boundary and owner. A local pg-llm-batch runtime defect returns to test-first repair. A central workflow/provider/permission failure remains a separate infrastructure or policy blocker and does not become a synthetic source finding.

If acceptance is unavailable because of a transient dependency, preserve the exact protected revision and retry only after evidence indicates the prerequisite changed or a bounded retry is justified. If the integrated change itself is unsafe, use the documented rollback or forward-repair path appropriate to the changed persistence/runtime boundary and then reacquire fresh evidence on the resulting protected state.

## Security, privacy, and governance impact

Operational evidence must remain least-privilege and data-minimized. It must not expose provider credentials, DSNs, prompt/result bodies, tenant identifiers, or other protected data unless a separately reviewed bounded evidence contract requires them. Formal independent approval, security checks, and protected-main operational acceptance remain distinct authorities; none substitutes silently for another.

## Compatibility and migration

This decision changes acceptance/governance semantics, not the package API or database schema. Existing PR evidence remains useful historical evidence for the source revision it actually exercised, but it cannot retroactively become protected-main operational evidence. New migration, deployment, scheduler, and release contracts should link to this ADR when post-merge proof is applicable.

## Verification

A compliant change records or can reconstruct:

- the exact protected-main source revision after integration;
- the capability-specific acceptance command/workflow and actual checked-out commit;
- the terminal operational result and material environment assumptions;
- any read-only dependency or infrastructure/policy blocker separately from source findings; and
- the relationship between that evidence and incident/release closure.

Repository documentation tests must keep this ADR indexed and traceable, and the release contract must preserve a distinct post-merge operational acceptance gate for runtime-sensitive changes.

## Rollback and supersession

Rollback of this governance rule means reverting the documentation/test contract in a reviewed change; it does not erase previously collected operational evidence. A superseding ADR must define an equal or stronger mechanism that binds integrated protected source identity to capability-specific runtime acceptance and explains how incident and release closure remain evidence-backed. Until then, source merge alone is never sufficient operational acceptance where the changed contract requires post-merge proof.
