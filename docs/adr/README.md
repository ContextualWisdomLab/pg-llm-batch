# Architecture Decision Record Index

## Authority

This index is a navigation and status aid for architecture decision records present on the protected default branch. The decision record itself remains normative for its context, decision, consequences, security boundary, and supersession rules.

The index intentionally does not embed an exact protected commit SHA. Pull requests, historical branches, generated merge commits, workflow runs, and review comments are evidence rather than durable architecture authority.

## Protected-main decisions

| ADR | Decision | Document status | Protected-main applicability |
| --- | --- | --- | --- |
| [0002](0002-tenant-scoped-lifecycle.md) | Tenant-scoped durable lifecycle state | Accepted | Defines trusted host-selected `tenant_scope`, tenant-qualified lifecycle identity, transaction-local RLS binding, and standalone compatibility. |
| [0003](0003-reproducible-release-evidence.md) | Reproducible release evidence before publication | Proposed | Records the reproducibility/evidence design while retaining the ADR's own `Proposed` status. Related implementation does not silently promote the decision status. |
| [0004](0004-descriptor-pinned-release-artifact-verification.md) | Descriptor-pinned release artifact verification | Proposed | Records descriptor-pinned TOCTOU hardening while retaining the record-local `Proposed` status. |
| [0006](0006-resumable-result-checkpoints.md) | Resumable provider-result checkpoints | Accepted | Defines immutable prefix checkpoint evidence and its prefix-only, non-authentication, non-whole-stream boundary. |
| [0007](0007-durable-result-checkpoint-store.md) | Durable tenant-isolated result checkpoint store | Accepted | Adds PostgreSQL persistence, tenant isolation, compare-and-swap concurrency, and a caller-owned transaction seam without a distributed exactly-once claim. |
| [0015](0015-http-425-too-early-retry.md) | HTTP 425 retry for bounded idempotent GETs | Accepted for the bounded retry slice | Keeps the default GET retry-status set closed, side-effecting POSTs single-attempt, and TLS/certificate/fingerprint failures outside automatic retry. |
| [0016](0016-postgres-logical-restore-seek.md) | PostgreSQL custom-format logical restore seek semantics | Accepted for the bounded direct-restore slice | Integrated with #212. Final descriptor EOF is not a completion invariant for random-access custom archives; archive metadata verification and transactional failure handling remain bounded by the executor contract. This decision does not establish backup creation, authenticated target isolation, post-restore application readiness, PITR, or RPO/RTO/HA/DR. |

Protected main also contains bounded PostgreSQL recovery-evidence primitives in `postgres_recovery_receipt.py`, `postgres_backup_evidence.py`, and `postgres_schema_evidence.py`. Their integration did not create an implicit ADR. They remain implementation/evidence contracts recorded by the PRD/TRD/traceability map. The direct logical-restore executor is separately governed by ADR 0016; executable logical backup and end-to-end recovery remain active/partial work.

## Numbering and missing identifiers

ADR numbers are stable identifiers, not a promise of contiguous numbering. A missing number does not establish that a decision is rejected, accepted elsewhere, or safe to reconstruct from an old branch. Gaps may reflect historical work, superseded proposals, unmerged branches, or reserved identifiers. Only a reviewed protected-main document may establish the status of a missing number.

New ADRs should use a repository-approved stable identifier rather than renumbering existing records. Renaming an integrated ADR changes external references and is an architecture-governance migration, not cosmetic cleanup.

## Decision status versus implementation status

ADR status answers whether an architectural decision is accepted, proposed, deprecated, or superseded. It is not interchangeable with product implementation status.

The canonical product/technical documents use `IMPLEMENTED-ON-PROTECTED-MAIN`, `ACTIVE-PR`, `PARTIAL`, `PLANNED`, and `SUPERSEDED` for implementation truth. A `Proposed` ADR can coexist with related code on protected main, and an `Accepted` ADR can describe a bounded decision whose larger product capability remains partial. Do not infer one status system from the other.

When an ADR and protected-main implementation appear inconsistent, treat the inconsistency as a defect to reconcile explicitly rather than editing the index to hide it.

## Supersession and amendments

A decision is superseded only when a reviewed record or amendment says so explicitly. A later implementation, issue, pull request, or historical branch does not implicitly supersede an ADR.

For a material architecture change:

1. refetch protected main and source/documentation writers touching the decision boundary;
2. identify existing ADRs and product/technical requirements that constrain the change;
3. record the decision or explicit amendment, including rejected alternatives and material operational/security consequences;
4. keep active/unmerged behavior classified as an overlay rather than protected-main truth;
5. update traceability after the capability reaches protected main; and
6. preserve standalone operation and modular MSA embedding unless a separately accepted decision changes that product contract.

## Non-guarantees that must remain visible

The current ADR set does not establish authentication from PostgreSQL RLS alone, provider authenticity from result checkpointing, full-stream immutability from a prefix checkpoint, distributed exactly-once processing, retry permission for arbitrary HTTP failures, backup restorability or PITR/RPO/RTO/HA/DR from recovery evidence or direct restore execution alone, or organizational security/compliance certification. Those boundaries must not be weakened by summaries, operator docs, marketing material, or future ADR titles.
