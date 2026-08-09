# Canonical Documentation Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository itself sufficient to reconstruct pg-llm-batch product intent, technical contracts, architecture, data model, operating model, evidence authority, and active-vs-shipped status without chat or PR-body archaeology.

**Architecture:** Add a canonical documentation graph rooted in a documentation fitness/index file. Separate protected-main as-built truth from active-PR target state, use Mermaid diagrams for UML/ERD, and make the documentation contract machine-checkable. Existing README, SECURITY, doctoring, and feature ADRs remain source material rather than being silently duplicated or reclassified.

**Tech Stack:** Markdown, Mermaid, Python/pytest contract tests, GitHub Actions, PostgreSQL DDL, Python package APIs.

## Global Constraints

- Protected `main` at plan creation is `bf2cc2e140dc3ff4a56c3203f80f41bb9fed5d10`; later evidence must refetch live refs.
- Never label ACTIVE-PR behavior as implemented on protected main.
- Use only repository-observed tables/APIs/workflows in as-built sections.
- Do not invent persistence to make an ERD look complete.
- Preserve standalone operation and modular MSA interoperability.
- Documentation is executable product/release evidence, not a substitute for source checks or independent review.
- Keep new documentation paths disjoint from active product branches where practical.

---

### Task 1: Documentation fitness contract

**Files:**
- Create: `tests/test_documentation_fitness_contract.py`
- Create: `docs/DOCUMENTATION_FITNESS.md`

**Interfaces:**
- Consumes: protected-main README, SECURITY, schema, public API, workflows, and active PR metadata.
- Produces: canonical file inventory, maturity vocabulary, and machine-checkable completeness contract.

- [ ] **Step 1: Write the failing contract test** requiring PRD, TRD, Architecture, UML, ERD, traceability, test strategy, operability, threat model, ADR index, and automation ADR files, plus the exact maturity/status vocabularies.
- [ ] **Step 2: Verify RED** through the repository CI path; missing canonical files must be the reason for failure.
- [ ] **Step 3: Add `docs/DOCUMENTATION_FITNESS.md`** with PRESENT-CURRENT/PRESENT-STALE/PARTIAL/MISSING/NOT-APPLICABLE/SUPERSEDED and IMPLEMENTED-ON-PROTECTED-MAIN/ACTIVE-PR/PARTIAL/ACCEPTED-ARCHITECTURE/PLANNED/RESEARCH-ONLY/SUPERSEDED/OUT-OF-SCOPE classifications.
- [ ] **Step 4: Keep the test RED** until the remaining canonical documents are added.

### Task 2: Product and technical requirements

**Files:**
- Create: `docs/product/PRD.md`
- Create: `docs/product/TRD.md`

**Interfaces:**
- Consumes: README, package public API, schema, existing product behavior, active PR queue.
- Produces: buyer/user/jobs-to-be-done/non-goals/acceptance requirements and implementation-quality/trust-boundary requirements.

- [ ] **Step 1:** Document product identity, target users, standalone and embedding use cases, buyer-visible outcomes, non-goals, and acceptance criteria.
- [ ] **Step 2:** Document technical constraints for PostgreSQL, provider HTTP, bounded resources, lifecycle durability, retries, observability, security, migrations, exact evidence, packaging, and release.
- [ ] **Step 3:** Mark every capability as protected-main, active PR, accepted target, planned, superseded, or out-of-scope.

### Task 3: Architecture, UML, and ERD

**Files:**
- Create: `ARCHITECTURE.md`
- Create: `docs/architecture/UML.md`
- Create: `docs/architecture/ERD.md`

**Interfaces:**
- Consumes: `pg_llm_batch/schema.sql`, public package API, CLI/runtime modules, Docker/health/readiness behavior.
- Produces: as-built component/deployment/authority views, behavior sequences/states, and persisted relational model.

- [ ] **Step 1:** Write root architecture with system context, module boundaries, trust/authority boundaries, data flow, runtime/deployment modes, and active-PR overlay.
- [ ] **Step 2:** Add Mermaid component, CLI/provider sequence, GET retry/response-handoff state, lifecycle persistence, health/readiness, standalone deployment, CWL embedding authority, and release/evidence diagrams.
- [ ] **Step 3:** Add Mermaid ERD for protected-main tables only, plus a separately labeled ACTIVE-PR conceptual extension section for tenant/checkpoint/audit features.
- [ ] **Step 4:** Cross-check every protected-main entity and relation against `schema.sql`.

### Task 4: Security, operations, testing, and traceability

**Files:**
- Create: `docs/THREAT_MODEL.md`
- Create: `docs/TEST_STRATEGY.md`
- Create: `docs/OPERABILITY.md`
- Create: `docs/TRACEABILITY.md`

**Interfaces:**
- Consumes: SECURITY policy, CI/test contracts, health behavior, migrations, active PR queue, product/TRD decisions.
- Produces: threat/control ownership, quality pyramid and acceptance evidence, runbook/recovery/SLO boundaries, and requirement-to-code/test/evidence mapping.

- [ ] **Step 1:** Threat-model credentials, provider input, database tenancy, resource exhaustion, SSRF/destination validation, secret disclosure, replay, stale evidence, supply chain, and writer races.
- [ ] **Step 2:** Specify deterministic unit/integration/security/concurrency/migration/release tests and exact-head evidence classification.
- [ ] **Step 3:** Specify startup/readiness, health, backup/recovery assumptions, migration/rollback, incident diagnostics, and release/operator acceptance.
- [ ] **Step 4:** Build a stable traceability matrix linking requirements/decisions to modules, schema, tests, active PRs, and evidence classes without embedding transient run IDs in timeless contracts.

### Task 5: Decision records for maintenance/evidence authority

**Files:**
- Create: `docs/automation/ADR-0001-work-conserving-maintenance.md`
- Create: `docs/automation/ADR-0002-evidence-identity-and-writer-lease.md`
- Create: `docs/adr/README.md`

**Interfaces:**
- Consumes: repository maintenance policy and current conversation decisions.
- Produces: durable status-bearing decisions for no-early-stop execution, writer leases, live source/base identity, evidence classes, and independent review separation.

- [ ] **Step 1:** Record the work-conserving no-early-stop decision, branch rotation, mandatory double exit sweep, and rollback/risks.
- [ ] **Step 2:** Record exact contributor-head/live-base identity, source-publication CAS boundaries, read-only dependencies, writer-conflict behavior, and review/check/evidence separation.
- [ ] **Step 3:** Add an ADR index that distinguishes repository product ADRs from automation-governance ADRs and prevents undocumented decisions from living only in chat/PR bodies.

### Task 6: Verify and publish

**Files:**
- Modify only if required by validation: the new canonical documentation and test files above.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: one reviewable main-compatible documentation authority PR.

- [ ] **Step 1:** Run/observe the documentation contract after all canonical files exist and verify GREEN.
- [ ] **Step 2:** Recheck protected main, branch head, active PR queue, and every named public table/API to catch drift introduced during the work.
- [ ] **Step 3:** Create a Draft PR if exact-head checks are still pending; mark Ready only when source-head verification supports it and review can proceed without violating other writer lanes.
- [ ] **Step 4:** Treat PR creation/green CI/review wait as intermediate and immediately resume other safe pg-llm-batch work.
