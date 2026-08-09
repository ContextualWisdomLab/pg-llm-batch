# ADR-0004: Separate semantic source review from infrastructure and policy evidence

- **Status:** ACTIVE-PR
- **Scope:** automated and human review evidence, infrastructure/policy merge-readiness, and source-finding authority

## Context

A pull-request review can become unavailable before a reviewer has enough evidence to assess source semantics. Coverage bootstrap, source materialization, a required check, a reviewer provider, branch policy, or another infrastructure dependency can fail even when no product-source defect has been established. The exact contributor head and live base may remain unchanged while that external evidence path is unavailable.

Historically, an automated review path can express such a failure as `CHANGES_REQUESTED`. That state is useful as a merge-readiness blocker, but it becomes misleading if the infrastructure failure is rendered as a synthetic source-code finding with an invented path, line, severity, root cause, or code-fix instruction. The repository already separates exact contributor head, PR-base snapshot, live base, synthetic integration revisions, checks, semantic review, and independent approval. This ADR makes the semantic-review versus infrastructure/policy distinction an explicit durable decision.

## Alternatives

1. **Translate every review-path failure into a source finding.** Rejected. Coverage bootstrap, runner, provider, permission, branch-policy, and other infrastructure failures do not prove a defect in the changed source.
2. **Ignore infrastructure failures and treat review as successful.** Rejected. Missing required evidence must fail closed for merge readiness and cannot be promoted to approval.
3. **Keep semantic source review and infrastructure or policy blocker evidence separate.** Chosen. The merge gate remains blocked where policy requires evidence, while semantic review uses `ABSTAIN` or an equivalent unavailable outcome until source-backed review can actually execute.

## Decision

### Semantic source review

A **semantic source review** is authoritative only for findings supported by changed or relevant source evidence tied to the exact contributor head and the reviewed live base or explicitly identified immutable base snapshot. A source finding must identify evidence that actually supports the claimed defect. Reviewer prose, severity, path/line attribution, root cause, and remediation must not be synthesized from an unrelated check, bootstrap, provider, permission, or policy failure.

### Infrastructure or policy blocker

An **infrastructure or policy blocker** is a separate evidence class. Examples include failed or unavailable coverage evidence, source-materialization transport failure, runner/DNS/provider outage, missing required check, reviewer rate limit, unavailable reviewer credential, missing independent approval, or branch-protection/ruleset rejection.

An infrastructure or policy blocker **must not become a source-code finding** unless an independent source-backed defect is also established. It may and often must keep merge readiness non-passing.

### Abstention semantics

When required source review cannot execute or cannot obtain the evidence needed to make a semantic judgment, the semantic outcome is **ABSTAIN** (or a machine-equivalent `UNAVAILABLE` state), not a fabricated source defect and not approval. `ABSTAIN` means the semantic question remains unanswered. It never converts missing evidence into success.

If the review system can publish only a coarse GitHub review state such as `CHANGES_REQUESTED`, the accompanying structured evidence must classify the cause as an infrastructure or policy blocker and explicitly state that semantic source review abstained. Downstream automation must not interpret the review body as a source-backed defect unless independent source evidence is present.

### Authority separation

The following remain distinct authorities:

- exact contributor head — the source revision proposed for integration;
- live base — the independently resolved current target-branch tip used for current compatibility decisions;
- check/workflow evidence — proof about the commit actually exercised;
- semantic source review — source-backed findings or an explicit abstention/unavailable result;
- infrastructure or policy blocker — a non-source gate that can block readiness;
- independent approval — qualifying non-author formal approval when live repository policy or governance requires it.

No status, comment, model output, infrastructure failure, or synthetic integration revision substitutes automatically for another authority.

## Consequences

The repository may show both a non-passing merge gate and zero source findings at the same time. This is intentional. It prevents false attribution to product code while preserving fail-closed governance. Operators and maintainers must repair the actual failing owner rather than mutating a clean leaf branch merely to obtain a different automation result.

Evidence envelopes and documentation may need an explicit blocker classification plus semantic `ABSTAIN`/`UNAVAILABLE` field. Existing GitHub review states remain usable as transport, but their body and downstream interpretation must preserve this distinction.

## Failure and recovery

When semantic review is unavailable:

1. preserve the exact contributor head and live base identities;
2. identify the first failing infrastructure or policy boundary and its owner;
3. do not create a synthetic path/line source defect;
4. repair the owning dependency when it is writable, or treat it as a read-only dependency when another repository owns it;
5. do not churn a clean leaf source head solely to retrigger the same broken external path;
6. after the prerequisite materially changes, rerun review on the unchanged exact head when still current; and
7. record any independently discovered source defect separately from the infrastructure blocker.

If a reviewer later obtains valid source evidence, that fresh exact-head semantic result supersedes the abstention for the reviewed revision. If the source head or relevant live base changes, prior semantic evidence must be re-evaluated according to repository policy.

## Security and governance impact

This decision is fail-closed. It does not waive coverage, security, branch protection, required review, or independent approval. It reduces the risk that infrastructure outages are misdiagnosed as code vulnerabilities, that maintainers make unnecessary source changes to satisfy synthetic findings, or that a genuine unavailable review is falsely presented as success.

The distinction also protects auditability: a diligence reviewer can tell whether a blocked merge is caused by source semantics, infrastructure, policy, or independent-approval governance instead of reconstructing that cause from prose.

## Compatibility and migration

No package runtime, database schema, provider protocol, CLI, or public Python API changes are required by this ADR. Review/evidence producers should migrate incrementally by adding explicit blocker classification and semantic abstention/unavailable semantics while retaining existing GitHub checks/reviews as transport where necessary.

Existing historical `CHANGES_REQUESTED` reviews caused solely by infrastructure or policy failure remain non-passing evidence until superseded by fresh review; they must not be retroactively relabeled as source defects.

## Verification

Acceptance requires machine-checkable or reviewable evidence that:

- infrastructure/policy failure and semantic source findings are represented separately;
- an unavailable semantic review records `ABSTAIN` or an equivalent unavailable outcome;
- no infrastructure-only failure fabricates a source path, line, severity, root cause, or code-fix instruction;
- the evidence records the exact contributor head and applicable live base identity;
- merge readiness remains fail-closed while required evidence is unavailable; and
- independent approval remains a separate authority where required.

Repository documentation and review workflows that claim this contract should include regressions for infrastructure-only failure, source-backed finding, semantic abstention, stale-head invalidation, and successful fresh-review recovery.

## Rollback and supersession

Rollback removes this explicit classification contract but must not convert infrastructure failures into source findings or approvals. A superseding ADR must preserve a falsifiable distinction between source-semantic evidence and non-source merge-readiness evidence, define unavailable-review behavior, retain exact contributor head and live base binding, and preserve independent approval as a separate authority. Until such an ADR is accepted, this decision remains the repository governance target.
