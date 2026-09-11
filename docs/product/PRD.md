# Product Requirements Document

## Document authority

This PRD is the canonical product-status contract for `pg-llm-batch`. Protected default-branch code, schema, tests, and accepted decisions are shipped authority. Pull requests, issue plans, historical branches, generated merge commits, exact SHAs, run IDs, and review commentary are evidence or work-in-progress rather than durable product truth.

Status vocabulary: **IMPLEMENTED-ON-PROTECTED-MAIN**, **ACTIVE-PR**, **PARTIAL**, **PLANNED**, and **SUPERSEDED**.

## Product purpose and users

`pg-llm-batch` is a standalone and embeddable PostgreSQL-centered engine for durable/asynchronous LLM Batch API workloads. It owns deterministic token/resource accounting, bounded JSONL preparation, package-owned PostgreSQL persistence, validated provider Batch API interaction, durable lifecycle/checkpoint state, tenant/RLS boundaries, bounded reconciliation, and bounded recovery controls without requiring a particular CWL host service.

Primary users are platform operators, application/platform engineers, multi-tenant hosts that authenticate and authorize callers before choosing `tenant_scope`, and reliability/security reviewers who need deterministic failure, migration, rollback, release, and evidence boundaries.

## Protected-main capability contract

| Capability | Status | Product boundary |
| --- | --- | --- |
| PostgreSQL token counting and bounded batch preparation | IMPLEMENTED-ON-PROTECTED-MAIN | Deterministic token/resource accounting and finite batch partitioning. |
| Disk-free package payload persistence | IMPLEMENTED-ON-PROTECTED-MAIN | Package JSONL/file/line/request state is durable PostgreSQL state, not a disposable local cache. |
| OpenAI-compatible upload/create/poll/wait/cancel/retrieve | IMPLEMENTED-ON-PROTECTED-MAIN | Provider destinations, identifiers, responses, downloads, retries, and waits are validated and bounded. |
| Standalone durable lifecycle | IMPLEMENTED-ON-PROTECTED-MAIN | `DurableBatchAPIClient` retains its four-argument recorder seam and explicit `standalone` scope. |
| Tenant-qualified lifecycle with forced RLS | IMPLEMENTED-ON-PROTECTED-MAIN | Trusted host-selected `tenant_scope` qualifies durable identity and is bound transaction-locally; arbitrary SQL, `SUPERUSER`, and `BYPASSRLS` remain outside the isolation guarantee. |
| Durable result checkpoint/CAS storage | IMPLEMENTED-ON-PROTECTED-MAIN | Tenant-qualified checkpoint authority and conflict detection; not distributed exactly-once. |
| Scheduler-independent bounded reconciliation | IMPLEMENTED-ON-PROTECTED-MAIN | Finite host-selected candidates use the reviewed provider client; discovery and scheduling remain separate. |
| Cross-process reconciliation single-flight | IMPLEMENTED-ON-PROTECTED-MAIN | Merged #191 provides tenant-qualified PostgreSQL session advisory-lock exclusion. It is not a scheduler, durable lease, result-application transaction, terminal-work-retirement mechanism, or distributed exactly-once guarantee. |
| Bounded recovery receipt / backup-artifact / packaged-schema evidence | IMPLEMENTED-ON-PROTECTED-MAIN | Content-free identity/integrity evidence only; not backup execution, provenance, restorability, live-schema parity, PITR, or RPO/RTO. |
| PostgreSQL logical backup execution | ACTIVE-PR | #208 remains a bounded `pg_dump` candidate; protected main must not be described as creating a restorable backup from evidence primitives alone. |
| PostgreSQL logical restore execution | IMPLEMENTED-ON-PROTECTED-MAIN | Merged #212 provides the bounded direct custom-format `pg_restore` executor. It accepts random-access seek behavior and verifies archive metadata instead of requiring final EOF. Closed #209 remains historical defect evidence. No `pg_dump`, target-authentication, application-readiness, PITR, or RPO/RTO/HA/DR guarantee follows. |
| PostgreSQL restore-target cluster identity verification | IMPLEMENTED-ON-PROTECTED-MAIN | Merged #228 provides `verify_postgres_restore_target_isolation(...)`: live and restore libpq service names must differ and caller-owned `pg_control_system().system_identifier` values must differ. The package does not open either connection, authenticate who collected the identities, accept a DSN, execute restore, or prove post-restore application/catalog/PITR/RPO-RTO readiness. |
| Recovery evidence binding / live reinspection | ACTIVE-PR | Composition or later re-hashing is not provenance, restorability, or target isolation. |
| Post-restore catalog/application readiness | ACTIVE-PR | #296 is an unshipped application-readiness candidate; branch GREEN is not protected-main truth. |
| Permanent live PostgreSQL integration lane | ACTIVE-PR | #341 executes the full integration marker on its branch and carries #296 as a tested child; the workflow is not protected authority until integration. |
| Physical/WAL/PITR recovery | ACTIVE-PR / PARTIAL | Intent/evidence candidates do not prove `pg_basebackup`, WAL replay, promotion, or achieved objectives. |
| End-to-end PostgreSQL recovery readiness | PARTIAL | Evidence, direct logical restore, and bounded name+cluster separation still do not prove an isolated restore with schema/RLS/constraint/extension parity, migration compatibility, external key/config custody, physical/WAL/PITR recovery, application readiness, or measured RPO/RTO/HA/DR. |
| Durable reconciliation candidate discovery | ACTIVE-PR | Discovery must be tenant-qualified, bounded, deterministic, and database-authoritative. |
| Autonomous package worker | PARTIAL | Reconciliation, transient single-flight, and durable state exist; a complete scheduler/crash-recovery/terminal-retirement control plane does not. |
| Durable result application coupled to checkpoint advancement | PARTIAL | Existing checkpoint/retrieval primitives do not establish end-to-end exactly-once result application. |
| Existing-volume legacy `http` / `pg_cron` retirement | ACTIVE-PR | Existing deployments require fail-closed, reversible migration evidence before legacy authority is retired. |
| PostgreSQL-backed configuration and secret storage | IMPLEMENTED-ON-PROTECTED-MAIN | Protected main supports optional Fernet plus explicit compatibility mode. `SecretStore(require_encryption=False)` can persist base64-obfuscated `is_encrypted = FALSE` rows. |
| Production secret-at-rest policy lifecycle | PARTIAL | Mandatory encryption, historical compatibility-row migration, key rotation/recovery, and external key custody are not protected guarantees; #210 remains stricter active work. |
| Redacted readiness and bounded diagnostics | IMPLEMENTED-ON-PROTECTED-MAIN | Public/operational evidence omits content-bearing lower-layer details. |
| First-class OpenTelemetry installation extra | ACTIVE-PR | Base installs remain telemetry-dependency-free until the optional graph integrates with lock/release evidence. |
| Standalone + modular embedding | IMPLEMENTED-ON-PROTECTED-MAIN | CWL services may integrate, but are not hidden runtime dependencies. |

## Functional requirements

### FR-1 — Batch preparation

Resolve a valid package batch identity, select eligible requests, count tokens through the reviewed PostgreSQL tokenizer boundary, partition under explicit token/byte/record/provider limits, and persist package-owned payload/file/line/request assignments atomically. Supported retries must not silently duplicate assignment or corrupt state.

### FR-2 — Provider interaction

Provider operations use validated endpoints and finite response/download budgets. Automatic retries are limited to reviewed idempotent GET behavior. Side-effecting POSTs do not gain implicit retry authority. Credentials and provider content are excluded from ordinary diagnostics.

### FR-3 — Durable lifecycle and tenancy

Tenant-aware clients validate trusted host-selected `tenant_scope` synchronously before observation reservation, credential lookup, provider I/O, or lifecycle SQL. The durable key is `(tenant_scope, endpoint_alias, remote_batch_id)` and tenant-aware writes/reads bind that scope through parameterized transaction-local PostgreSQL context with forced RLS. `pg_llm_batch.tenant_scope` is routing context, not authentication. A role capable of arbitrary SQL can set it arbitrarily, so host identity mapping, authorization, SQL-injection prevention, and administrative database roles remain outside the RLS guarantee.

Standalone compatibility is normative: `DurableBatchAPIClient` retains `(postgres_dsn, endpoint_alias, provider_batch, observation_order)` and explicit `standalone` persistence/read scope.

### FR-4 — Reconciliation and provider-effect recovery

Reconciliation is finite, deterministic, payload-free in operational evidence, and reuses the validated provider-client boundary. Protected main supplies transient tenant-qualified session advisory single-flight. Candidate discovery, scheduling, durable leasing, result application, terminal-work retirement, and cross-system exactly-once semantics are separate capabilities. Provider-success/database-failure states remain observable rather than being rewritten as if the provider effect never occurred.

### FR-5 — Persistence and PostgreSQL recovery

Package-owned database objects use explicit durable identities, parameterized SQL, synchronized schema copies where required, and documented migration/rollback boundaries. Malformed durable state fails closed before downstream effects when correctness depends on it.

Protected main contains bounded content-free recovery evidence, the bounded #212 logical restore executor, and the bounded #228 restore-target name+cluster-identity verifier. The verifier requires distinct exact libpq service names and distinct caller-owned PostgreSQL `system_identifier` values gathered from already-opened connections. It does not establish connection provenance or authorize destructive action. The logical restore executor does not create backups or prove target/application readiness. End-to-end recovery still requires independent backup authority, authenticated target provenance, post-restore schema/RLS/constraint/extension/application acceptance, migration compatibility, key/config custody, and physical/WAL/PITR evidence where claimed.

### FR-6 — Configuration and secrets

Configuration and secrets are PostgreSQL-backed. Fernet is optional on protected main. Compatibility mode may store base64-obfuscated rows with `is_encrypted = FALSE`; this is not an encryption-at-rest claim. Deployments may require Fernet explicitly, but mandatory-default policy, migration of historical compatibility rows, rotation/recovery, and external key custody require separately integrated contracts. Environment variables are bootstrap transport only where documented; embedding hosts may inject credential providers.

### FR-7 — Observability and diagnostics

Operational telemetry is opt-in. Finite operation/outcome vocabularies may be emitted; prompts, provider bodies, credentials, arbitrary endpoint aliases/resource IDs, and arbitrary exception text are not telemetry attributes. Public readiness uses bounded categories where lower-layer text could contain sensitive data.

### FR-8 — Deployment

The package remains usable without `contextual-orchestrator`, `naruon`, or another CWL repository. Host services may supply authentication, tenant routing, secret resolution, gateway/model routing, OpenTelemetry export, or scheduling through explicit seams.

## Non-functional requirements

Owned production Python maintains exact 100% statement/branch coverage and complete public docstrings under repository gates. Supported validation includes Python 3.10, 3.12, and 3.14 plus realistic PostgreSQL/container integration when behavior depends on PostgreSQL.

Security-sensitive validation fails closed. Authorized business payloads are not silently masked or transformed: doing so changes token counts, provider semantics, persisted evidence, replay, and business meaning. Confidentiality is enforced at explicit authentication/authorization, database/service, transport/storage, retention, and operational-evidence boundaries. Any content transformation is an explicit host/business policy with provenance and acceptance evidence.

Network, response, retry, wait, candidate-scan, payload, recovery, and release-evidence work is explicitly bounded. Queued, skipped, cancelled, absent, stale, predecessor-head, synthetic-only, or infrastructure-failed evidence is not exact-head success.

Dependencies and release artifacts are locked/reproducible according to repository policy. Release acceptance covers the then-live quality, security, package/container, SBOM, provenance, artifact-identity, rollback/recovery, review, and governance gates on the exact integrated protected head. A version string or successful PR does not imply publication.

## Explicit non-goals

- Replacing host authentication or authorization.
- Treating RLS or `tenant_scope` as a credential or SQL-injection prevention.
- Making provider/model content an authority for tenant, endpoint, credential, or filesystem selection.
- Reintroducing provider networking or independent scheduling inside PostgreSQL.
- Inferring restorability, target provenance, PITR, RPO/RTO/HA/DR, or compliance from recovery hashes, a restore command, or `system_identifier` comparison alone.
- Claiming distributed exactly-once processing without an integrated transaction/recovery contract spanning every external effect.
- Requiring a particular CWL host service for standalone use.
- Claiming SOC 2, CSAP, or another certification from repository evidence alone.

## Product acceptance boundary

A capability moves to **IMPLEMENTED-ON-PROTECTED-MAIN** only after its unchanged source satisfies the live ruleset, required exact-head quality/security/coverage/package/provenance/release evidence, valid review findings, and protected-default-branch integration. Canonical documentation is then refreshed from the resulting protected tree; predecessor evidence never transfers automatically.
