# ADR-0003: Canonical documentation authority

Status: ACTIVE-PR

## Context

pg-llm-batch has durable product, technical, security, data, operability, release, and automation decisions that cannot safely live only in chat, pull-request bodies, scheduler prompts, or scattered feature doctoring. Protected main is the runtime and shipped-behavior authority, while an active PR may contain complete proposed documentation without making that proposal shipped truth.

A documentation file can also exist and still be stale, partial, or classify an active implementation as protected behavior. File presence alone is therefore not a sufficient acquisition-readiness control. The repository needs a canonical documentation graph, a documentation fitness model, explicit capability maturity, and machine-checkable consistency tests that bind prose and diagrams to source, schemas, workflows, public interfaces, and live implementation state.

## Decision drivers

- A buyer or maintainer must be able to reconstruct the product without conversation history.
- Protected-main behavior, active implementation, accepted architecture, and planned work must never be conflated.
- PR numbers, SHAs, run IDs, and provider status are volatile evidence, not timeless architecture.
- A stale document can create security, migration, support, and release risk even when CI for production code is green.
- Documentation maintenance must remain work-conserving and must not become a reason to stop while executable product work remains.

## Alternatives considered

1. **Keep architecture intent in chat and PR descriptions.** Rejected because those surfaces are difficult to discover, are not versioned with the product authority graph, and cannot be validated by repository tests.
2. **Treat README plus feature doctoring as sufficient.** Rejected because neither provides a complete requirements, architecture, data, security, operability, release, and traceability spine.
3. **Require canonical filenames without semantic validation.** Rejected because existence checks cannot detect stale capability status, wrong API surfaces, incorrect ERD ownership, or contradictory diagrams.
4. **Maintain one indexed canonical graph with explicit fitness and maturity plus machine-checkable contracts.** Chosen.

## Decision

The repository maintains one discoverable canonical graph, indexed from README, with repository-convention equivalents of:

- product requirements (PRD);
- technical requirements (TRD);
- root architecture and bounded-context views;
- public API, CLI, schema, and versioning contracts;
- UML behavioral/deployment/authority views;
- ERD or logical data model that distinguishes persisted from conceptual entities;
- security policy and threat model;
- test strategy;
- operability, recovery, migration, and rollback guidance;
- release acceptance and provenance requirements;
- requirements/decision/standard/research-to-code/test/evidence traceability;
- ADR index and detailed decisions; and
- a documentation fitness and capability-maturity matrix.

Protected main remains the shipped implementation authority. An active PR is never described as implemented on protected main merely because its source, tests, or documentation are complete. The canonical graph uses the repository's closed fitness and maturity vocabularies and keeps qualifiers, PR identities, and dated evidence separate from those status values.

Durable decisions established through conversation or automation prompts must be revalidated against live repository state and then moved into the appropriate canonical document or ADR. Chat and scheduler prompts may coordinate work, but they are not architecture authority.

## Documentation fitness and machine-checkable enforcement

Documentation fitness is evaluated semantically, not by filename existence alone. Repository tests should, where practical:

- require canonical files and index links;
- validate the closed fitness and maturity vocabulary;
- compare documented package exports and CLI commands with source-derived surfaces;
- bind protected-main and ACTIVE-PR ERD entities to the correct sections;
- validate ADR index/status consistency;
- validate Mermaid/code-block structure and important state/sequence ordering;
- detect stale product, workflow, capability, and ownership names; and
- prevent an active PR or superseded implementation from being promoted to protected-main truth.

A documentation test is evidence for the checked revision only. It does not substitute for source tests, security checks, semantic review, branch policy, independent approval, or protected-main operational acceptance.

## Consequences

The repository carries more explicit documentation and contract tests, and material product changes may require a small documentation follow-through. In exchange, product intent, implementation maturity, trust boundaries, and release evidence remain auditable and acquisition diligence does not depend on reconstructing historical conversation.

The graph may intentionally mark AGENTS, CLAUDE, or another shared surface PARTIAL while overlapping implementation branches are moving. Visible incompleteness is preferable to a competing writer or a false completeness claim.

## Failure and recovery

If canonical documentation contradicts protected main, protected-main code/schema/workflow is immediate runtime truth and the affected documentation is classified stale until repaired. If a live implementation branch changes, refresh the relevant maturity and traceability claims rather than preserving an obsolete PR snapshot. If another writer is actively changing the canonical documentation branch, freeze that branch and rotate to other safe repository work.

If a documentation test fails because the document is wrong, repair the smallest authoritative document. If it fails because the test encodes stale or overly broad assumptions, repair the test without weakening the semantic contract. Neither case justifies bypassing normal review or release gates.

## Security, privacy, and governance impact

Documentation is part of the control surface for credentials, provider egress, tenant isolation, migration safety, data retention, release provenance, and review evidence. Incorrect maturity or ownership claims can cause real operational harm. Security and privacy claims therefore follow the same protected-main-versus-active distinction as functional capabilities, and documentation must not claim certification or controls that are not evidenced.

## Compatibility and migration

This decision does not change runtime APIs, database schemas, or provider protocols. Existing strong documentation is consolidated or indexed rather than duplicated. When older documentation conflicts with the canonical graph, mark it SUPERSEDED or update it through normal reviewed change; do not silently maintain two authorities.

## Verification and acceptance

Acceptance of this decision requires:

1. the canonical graph and ADR index are discoverable from the repository;
2. the fitness and maturity vocabulary is explicit;
3. protected-main and active-PR claims are separated;
4. machine-checkable documentation contracts cover material structural and source-bound claims;
5. traceability links material requirements and decisions to implementation/tests/evidence; and
6. normal exact-revision CI, security, review, branch-policy, and release gates remain independent and are not waived by documentation completeness.

## Rollback

If this ADR is reverted, the repository must retain an equivalent reviewed authority model before removing the canonical graph or its semantic tests. Rollback must not return durable architecture to chat-only or PR-body-only state and must not collapse protected-main and active-PR maturity.

## Supersession

A superseding ADR must define the replacement source-of-truth graph, status/maturity semantics, machine-checkable consistency strategy, migration of existing canonical documents, and rules preventing planned or active work from being presented as shipped behavior. Until such a decision is reviewed, this ADR remains the canonical documentation-authority target.
