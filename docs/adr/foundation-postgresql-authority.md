# ADR: PostgreSQL durable authority and disk-free batch state

## Status and maturity

**IMPLEMENTED-ON-PROTECTED-MAIN.** This ADR records the protected-main architecture represented by the repository baseline referenced from `ARCHITECTURE.md`. It does not promote checkpoint, audit, tenant-RLS, or other ACTIVE-PR persistence overlays to shipped behavior.

## Context and decision drivers

`pg-llm-batch` prepares provider batch work from database-backed requests and must remain restartable, inspectable, and usable both as a standalone component and as an embedded Python package. Batch preparation also handles prompt/request material that should not require package-owned temporary JSONL files merely to cross internal component boundaries.

The durable design therefore needs one transactional authority for package configuration, queue/batch/request state, payload reconstruction, endpoint/model mapping, and the current remote-lifecycle projection. It must support deterministic preparation, explicit rollback, and a disk-free payload path without inventing a second persistence plane.

## Alternatives considered

1. **Package-owned temporary files as the primary batch authority.** Rejected because filesystem lifecycle, permissions, cleanup, crash recovery, and container-volume semantics would become a second authoritative state machine.
2. **In-memory-only preparation.** Rejected because process restart would destroy reconstruction and reconciliation state.
3. **An external object store or message bus as mandatory infrastructure.** Rejected for the base product because it would weaken standalone operation and add a second required service before the package has a product need that PostgreSQL cannot satisfy.
4. **PostgreSQL as the package-owned durable authority with virtual payload reconstruction.** Chosen because the product already requires PostgreSQL for request/configuration state and can keep preparation mutations transactionally coherent.

## Decision

PostgreSQL is the durable authority for package-owned configuration/secrets, queue and batch state, request assignments, JSONL line state, payload documents, endpoint/model mapping, and the protected-main `llm_remote_batch_jobs` lifecycle projection.

Batch preparation remains **disk-free** from the package's perspective: payload bytes are persisted in PostgreSQL and exposed through the virtual `memory://<file_id>` reconstruction path rather than through package-owned temporary payload files. `PostgresBatchOrchestrator.prepare_batches()` performs preparation under the database transaction/advisory-lock contract described by the implementation and canonical architecture.

This decision does not require embedding hosts to place their own user identity, tenant directory, global audit store, or unrelated application data into pg-llm-batch tables.

## Consequences and non-goals

- PostgreSQL availability and migration correctness are part of product availability.
- The package gains one durable reconstruction point for batch preparation instead of filesystem/database split-brain state.
- Database administrator and superuser capabilities remain outside package-enforced confidentiality/integrity guarantees.
- PostgreSQL authority does **not** create distributed exactly-once semantics across PostgreSQL and an external provider or business system.
- ACTIVE-PR checkpoint/audit/RLS tables remain separately versioned targets until protected integration.

## Failure and recovery

A preparation exception before transaction commit rolls back the preparation transaction rather than publishing a partially committed file/request/line assignment from that invocation. A database failure before an external provider operation prevents that operation when the required state cannot be established.

Provider-success/database-failure is a different boundary handled by the lifecycle-observation decision: once an external provider effect has succeeded, a later PostgreSQL persistence failure is reconciliation evidence and must not be rewritten as if no external effect occurred.

Recovery uses the canonical schema, idempotent/restart-safe package operations where defined, reviewed forward/rollback migrations, and host-owned database backup/restore procedures. Rollback must not silently erase durable evidence.

## Security, privacy, and governance impact

PostgreSQL can contain prompts, request metadata, provider identifiers, configuration, and secret material. Deployments therefore need least-privilege database identities, transport encryption where required, host-owned backup/retention controls, and controlled administrator access. `SecretStore` encryption protects configured secret values when a Fernet key is supplied; it is not a substitute for database or host authorization.

Tenant-qualified row isolation is not claimed on the protected-main lifecycle schema. That boundary belongs to ACTIVE-PR #53 until integrated and verified.

## Compatibility and migration

The package schema and bundled PostgreSQL image are versioned product interfaces. Schema changes require forward/rollback treatment, package/container consistency, and compatibility tests appropriate to the changed objects. An embedding host may use an existing PostgreSQL deployment, but it must satisfy the package's required extensions/schema/runtime contract.

Replacing PostgreSQL as the base durable authority would be a breaking architectural change requiring an explicit data migration/export path and a superseding ADR.

## Verification and acceptance

Acceptance is grounded in protected-main schema/orchestrator/database tests, virtual-payload reconstruction tests, transactional failure tests, supported-version CI, and the repository's statement/branch/docstring gates. Documentation must distinguish protected-main tables from ACTIVE-PR conceptual/persisted overlays in the ERD and traceability matrix.

## Rollback and supersession

A faulty schema or preparation change is rolled back through the reviewed migration/revert path while preserving recoverable durable data. This ADR may be superseded only by a decision that names the replacement durable authority, proves migration and rollback semantics, preserves standalone/embedded compatibility or explicitly changes that product requirement, and updates PRD/TRD/Architecture/ERD/operability together.