# Architecture Decision Record Index

## Authority

This index is a navigation and status aid for architecture decision records that exist on protected `main`. The decision record itself remains the normative source for its context, decision, consequences, security boundary, and supersession rules.

The protected-main tree used to reconstruct this index is `d0a4b30be1f46536e352443309f3a35533156767`. A pull request, historical branch, generated merge commit, workflow run, review comment, or proposed file that is not on protected main is not silently promoted into this index.

## Protected-main decisions

| ADR | Decision | Document status | Protected-main applicability |
| --- | --- | --- | --- |
| [0002](0002-tenant-scoped-lifecycle.md) | Tenant-scoped durable lifecycle state | Accepted | Defines trusted host-selected `tenant_scope`, tenant-qualified durable lifecycle identity, transaction-local RLS binding, and the standalone compatibility scope. |
| [0003](0003-reproducible-release-evidence.md) | Reproducible release evidence before publication | Proposed | Documents the reproducibility/evidence design present in the repository. The ADR's own `Proposed` status is retained and must not be rewritten as architectural acceptance merely because related release-evidence code or workflows exist. |
| [0004](0004-descriptor-pinned-release-artifact-verification.md) | Descriptor-pinned release artifact verification | Proposed | Documents the descriptor-pinned TOCTOU-hardening design. Its `Proposed` decision status remains authoritative until explicitly changed through reviewed documentation governance. |
| [0006](0006-resumable-result-checkpoints.md) | Resumable provider-result checkpoints | Accepted | Defines immutable prefix checkpoint evidence and its explicit prefix-only, non-authentication, non-whole-stream assurance boundary. |
| [0007](0007-durable-result-checkpoint-store.md) | Durable tenant-isolated result checkpoint store | Accepted | Adds optional PostgreSQL persistence, tenant isolation, compare-and-swap concurrency, and a caller-owned transaction seam without claiming distributed exactly-once delivery. Depends on ADR 0006. |
| [0015](0015-http-425-too-early-retry.md) | HTTP 425 retry for bounded idempotent GETs | Accepted for the bounded retry slice | Keeps the default GET retry-status set closed, side-effecting POSTs single-attempt, and TLS/certificate/fingerprint failures outside automatic retry. |

## Numbering and missing identifiers

ADR numbers are stable identifiers, not a promise of contiguous numbering. The absence of `0001`, `0005`, or `0008` through `0014` from the protected-main directory does **not** mean those decisions are missing, rejected, accepted elsewhere, or safe to reconstruct from old branches. Gaps may reflect historical work, superseded proposals, unmerged branches, or reserved identifiers. Only a reviewed protected-main document may establish the status of a missing number.

New ADRs should use the next repository-approved stable identifier rather than renumbering existing records. Renaming an integrated ADR changes external references and should be treated as an architecture-governance migration, not cleanup.

## Decision status versus implementation status

ADR status answers whether an architectural decision has been accepted, proposed, deprecated, or superseded. It is not interchangeable with product implementation status.

The canonical product/technical documents use `IMPLEMENTED-ON-PROTECTED-MAIN`, `ACTIVE-PR`, `PARTIAL`, `PLANNED`, and `SUPERSEDED` for implementation truth. A `Proposed` ADR can coexist with related code on protected main, and an `Accepted` ADR can describe a bounded contract whose larger product capability is still only partial. Do not infer one status system from the other.

When an ADR and protected-main implementation appear inconsistent, treat the inconsistency as a defect to reconcile explicitly. Do not silently edit the index to make the conflict disappear.

## Supersession and amendments

A decision is superseded only when a reviewed record or amendment says so explicitly. A later implementation, issue, pull request, or historical branch does not implicitly supersede an ADR.

For a material architecture change:

1. refetch protected main and all source/documentation writers touching the decision boundary;
2. identify the existing ADRs and product/technical requirements that constrain the change;
3. record the new decision or explicit amendment, including rejected alternatives and operational/security consequences where material;
4. keep active/unmerged behavior classified as an overlay rather than protected-main truth;
5. update traceability after the capability actually reaches protected main; and
6. preserve standalone operation and modular MSA embedding unless a separately accepted decision changes that product contract.

## Non-guarantees that must remain visible

The current ADR set does not establish authentication from PostgreSQL RLS alone, provider authenticity from result checkpointing, full-stream immutability from a prefix checkpoint, distributed exactly-once processing, retry permission for arbitrary HTTP failures, or organizational security/compliance certification. Those boundaries must not be weakened by summaries, operator docs, marketing material, or future ADR titles.