# Architecture Decision Record Index

## Authority

This index is a navigation/status aid for ADRs present on the protected default branch. Each ADR remains normative for its own context, decision, consequences, security boundary, and supersession rules. Exact protected/contributor SHAs, workflow runs, generated merge commits, and review comments are intentionally excluded from durable architecture authority.

## Protected-main decisions

| ADR | Decision | Document status | Protected-main applicability |
| --- | --- | --- | --- |
| [0002](0002-tenant-scoped-lifecycle.md) | Tenant-scoped durable lifecycle state | Accepted | Trusted host-selected `tenant_scope`, tenant-qualified identity, transaction-local RLS binding, and standalone compatibility. |
| [0003](0003-reproducible-release-evidence.md) | Reproducible release evidence before publication | Proposed | Retains record-local `Proposed` status even where related implementation exists. |
| [0004](0004-descriptor-pinned-release-artifact-verification.md) | Descriptor-pinned release artifact verification | Proposed | Retains record-local `Proposed` status; implementation presence does not silently accept the decision. |
| [0006](0006-resumable-result-checkpoints.md) | Resumable provider-result checkpoints | Accepted | Immutable prefix checkpoint evidence; not provider authentication or whole-stream immutability. |
| [0007](0007-durable-result-checkpoint-store.md) | Durable tenant-isolated result checkpoint store | Accepted | PostgreSQL persistence, tenant isolation, CAS concurrency, and caller-owned transaction seam without distributed exactly-once. |
| [0015](0015-http-425-too-early-retry.md) | HTTP 425 retry for bounded idempotent GETs | Accepted for the bounded retry slice | Keeps the automatic GET retry set closed and side-effecting POSTs single-attempt. |
| [0016](0016-postgres-logical-restore-seek.md) | PostgreSQL custom-format logical restore seek semantics | Accepted for the bounded direct-restore slice | Integrated with #212. Final descriptor EOF is not a valid completion invariant for random-access custom archives; metadata verification and transactional failure semantics remain bounded by the executor. No backup, target-authentication, application-readiness, PITR, or RPO/RTO/HA/DR guarantee follows. |
| [0022](0022-postgres-restore-target-isolation.md) | Restore-target service-name and PostgreSQL cluster-identity separation | Accepted for the bounded restore-target identity seam | Integrated with merged #228. Exact live/restore service names and caller-owned `pg_control_system().system_identifier` values must differ. The package does not open/authenticate connections, accept DSNs/passwords, execute restore, or prove application/PITR/RPO-RTO readiness. |

Protected main also contains bounded recovery-receipt/artifact/schema evidence primitives. Their integration does not create implicit ADRs. Direct logical restore is governed by ADR 0016; bounded restore-target cluster separation is governed by ADR 0022. Logical backup, post-restore application acceptance, physical/WAL/PITR recovery, external key custody, and end-to-end recovery remain separately governed capabilities.

## Numbering and missing identifiers

ADR numbers are stable identifiers, not a promise of contiguous numbering. Missing numbers may reflect historical work, superseded proposals, unmerged branches, or reserved identifiers. A gap does not authorize reconstruction from an old branch. New records use a repository-approved stable identifier; renaming an integrated ADR is an architecture-governance migration rather than cosmetic cleanup.

## Decision status versus implementation status

ADR status is not product implementation status. Canonical product documents use `IMPLEMENTED-ON-PROTECTED-MAIN`, `ACTIVE-PR`, `PARTIAL`, `PLANNED`, and `SUPERSEDED`. A `Proposed` ADR may coexist with code on protected main, while an `Accepted` ADR may govern only a bounded slice of a larger partial capability. When ADR and protected implementation appear inconsistent, reconcile the defect explicitly rather than hiding it in the index.

## Supersession and amendments

A decision is superseded only by an explicit reviewed record/amendment. Later code, issues, PRs, or historical branches do not implicitly supersede it. Material changes require a fresh read of protected source and adjacent writers, explicit alternatives/rejected reasons/consequences, correct active-vs-shipped classification, and traceability refresh after integration.

## Non-guarantees

The ADR set does not establish authentication from RLS, provider authenticity from checkpointing, distributed exactly-once processing, arbitrary HTTP retry permission, backup restorability, authenticated connection provenance, post-restore application readiness, PITR/RPO/RTO/HA/DR from recovery evidence/direct restore/`system_identifier` comparison alone, or organizational certification.
