# ADR-0006: Scheduler failure recovery and continuation

- **Status:** ACTIVE-PR
- **Decision owner:** pg-llm-batch repository governance
- **Scope:** hourly autonomous maintenance scheduler/control-plane recovery

## Context

The autonomous maintenance contract can fail before useful repository work begins or can surface only a generic scheduled-task failure. A message such as **generic scheduled-task failure** is not evidence that `pg-llm-batch` source, tests, pull requests, or protected `main` are defective. It is evidence that the automation control plane failed to complete or report its intended execution.

A second failure mode is self-amplifying recovery: reacting to a scheduler problem by creating another scheduler, disabling the existing task without evidence, or repeatedly appending prompt history until prompt size and transport complexity themselves become failure risks. Those remedies can create duplicate writers, conflicting leases, and less reliable execution.

A third failure mode is **silent completion**: the invocation returns empty user-visible output, a generic failure banner, or a prompt-update acknowledgement without performing or proving any repository work even though a safe lane exists. Silence is not success evidence. It hides whether the scheduler failed before execution, exhausted its practical budget, lost connector authority, encountered a writer conflict, or simply stopped early.

The repository already requires work-conserving continuation through ADR-0001 and exact evidence/writer leases through ADR-0002. Scheduler recovery therefore needs a bounded handoff into those existing authorities rather than a parallel execution model.

## Drivers

- distinguish scheduler/control-plane failure from repository failure;
- preserve one authoritative enabled hourly task rather than multiplying writers;
- keep prompt size and transport complexity bounded and reviewable;
- make a user report of premature stopping or empty user-visible output actionable control evidence;
- ensure user redirection resumes a material safe repository action whenever one exists;
- recover into real repository work in the **same invocation** whenever safe work exists;
- reject silent completion and prompt-only completion as recovery outcomes; and
- retain the normal double exit sweep instead of treating scheduler repair as completion.

## Alternatives considered

### A. Treat a generic scheduler error as a repository blocker

Rejected. It conflates automation transport/execution failure with product state and can freeze unrelated repository work without source evidence.

### B. Create a replacement scheduler after each generic failure

Rejected. Duplicate schedulers create competing writer paths, violate the single-writer lease, and make failure attribution harder.

### C. Disable the current scheduler and wait for manual repair

Rejected as the default. Disabling a still-enabled, recoverable task turns a bounded control incident into lost continuation. Disablement is appropriate only when live evidence proves the existing scheduler is unsafe and a reviewed recovery explicitly requires it.

### D. Revalidate the control plane, compact it when needed, then resume the existing work-conserving loop

Chosen. The recovery first determines whether the configured hourly task is still enabled and authoritative, whether the failure is scheduler/prompt/tool related, and whether repository state remains independently actionable. Prompt repair replaces obsolete/redundant clauses when prompt size or transport complexity is implicated instead of endlessly appending history. Recovery then hands back to normal pg-llm-batch execution.

### E. Treat an empty response or prompt-update acknowledgement as successful recovery

Rejected. **Prompt repair alone is not recovery**, and empty user-visible output cannot distinguish a genuine all-lanes-exhausted exit from a pre-execution or premature-stop defect. The invocation must either produce exact evidence that no safe lane remains or resume material repository work.

## Decision

1. A **generic scheduled-task failure** is classified as a **control-plane incident** until evidence establishes a repository failure.
2. Refetch the configured automation and live GitHub repository state before choosing a remedy. Scheduler state and repository state are independent evidence classes.
3. If the authoritative **enabled hourly task** remains enabled, **do not create a duplicate scheduler** and do not disable it merely to clear an error message.
4. Distinguish activation/scheduling, prompt serialization or size, tool/connector execution, authentication/permission, and repository-operation failures before mutation.
5. When **prompt size** or transport complexity is a plausible cause, compact the existing prompt by replacing obsolete/redundant clauses while preserving writer lease, work conservation, evidence identity, merge gates, and double-exit semantics. Do not grow the prompt indefinitely as an incident log.
6. Prompt or scheduler repair is intermediate. **Prompt repair alone is not recovery.** If any safe pg-llm-batch work exists, execute a **material safe repository action** in the **same invocation** after recovery.
7. A user report that the loop stopped early, did nothing, returned **empty user-visible output**, or ended after prompt/documentation work is **user redirection** and evidence of a possible continuation-control defect. Re-evaluate the exit condition, missed queue lanes, scheduler contract, and last material repository action before resuming work.
8. **Silent completion** is prohibited while any material safe repository action exists. The absence of routine reporting does not permit the absence of repository execution or exact no-work proof.
9. Before terminating after recovery, apply the normal **double exit sweep** from ADR-0001. A repaired scheduler does not waive any source, review, security, branch-protection, or release gate.

## Compact prompt source

`docs/automation/HOURLY_WRITER_PROMPT.md` is the discoverable **compact hourly writer prompt** source for the one authoritative external hourly task. It delegates detailed product and architecture truth to the repository canonical documents, excludes transient full commit identities, and is machine-checked for size and required writer/evidence/exit semantics. The file is not scheduler activation or run-success evidence; external scheduler state must still be refetched independently.

## Failure and recovery procedure

1. Read the authoritative task state: enabled/disabled, cadence, last-run evidence, and current prompt identity.
2. Refetch protected `main`, open PR/issue state, active writer evidence, and the exact branch that was expected to change.
3. Classify the first failing boundary as scheduler/activation, prompt/transport, tool/connector, credentials/permissions, external dependency, repository behavior, or silent/premature completion.
4. Generate distinct bounded remedies and verify feasibility. Prefer retaining the existing scheduler and reducing prompt/control complexity over adding execution paths.
5. Apply the smallest safe control-plane repair.
6. Immediately select the highest-value non-conflicting pg-llm-batch repository action and continue in the same invocation. After user redirection, complete at least one **material safe repository action** when one exists before considering termination.
7. Revalidate changed repository state and finish with the ordinary double exit sweep.
8. If no material safe repository action exists, preserve exact evidence for that conclusion; do not substitute silent completion or empty user-visible output for the exit proof.

If the scheduler cannot be repaired autonomously because an external permission, authentication boundary, or platform safety policy is genuinely unavailable, record that prerequisite once and continue any repository work that does not depend on it.

## Security and governance impact

This decision reduces duplicate-writer risk and prevents a generic scheduler symptom from being converted into invented repository findings. It also makes no-op and silent outcomes observable without requiring routine status narration. It does not authorize bypassing branch protection, creating credentials, weakening tests, manufacturing reviews, modifying read-only dependency repositories, or racing another writer. Repository mutation still requires the ADR-0002 pre-write exact-head/base/blob/ref checks.

## Acceptance evidence

Recovery is acceptable when evidence shows all applicable properties:

- one authoritative hourly scheduler remains identifiable;
- no duplicate scheduler was introduced as a reflexive remedy;
- the failure boundary is classified separately from repository findings;
- prompt compaction, when used, preserves the required execution and governance contracts;
- the compact hourly writer prompt remains within its machine-checked size/evidence contract;
- prompt repair alone is not recovery;
- user redirection leads to a material safe repository action when one exists;
- silent completion and empty user-visible output are not used as substitutes for execution or exact exit evidence;
- a safe material repository action is resumed in the same invocation when one exists; and
- termination follows the ADR-0001 double exit sweep rather than the scheduler repair event.

A generic error banner, empty user-visible output, silent completion, or a prompt-update success message is not acceptance evidence by itself.

## Rollback

If this recovery policy causes unsafe scheduler retention or makes incidents harder to isolate, revert the control-plane changes to the last known reviewed scheduler prompt/configuration and keep repository writes stopped only for the affected automation lane. Do not roll back product source solely because scheduler recovery failed. Retain the prohibition on duplicate writers and require exact exit evidence even during rollback.

## Supersession

A future ADR may supersede this decision only by defining an equally explicit scheduler authority, duplicate-writer prevention mechanism, repository-vs-control-plane evidence boundary, bounded prompt lifecycle, same-invocation handoff rule, user-redirection rule, silent-completion prohibition, rollback path, and termination sweep.
