# Technical Requirements Document

## Document authority

This TRD defines technical invariants for `pg-llm-batch`. Protected default-branch code, schema, tests, and accepted decisions are stronger authority than historical branches, stale PR prose, predecessor checks, exact SHAs, generated merge commits, or run IDs. Status vocabulary is shared with the PRD: **IMPLEMENTED-ON-PROTECTED-MAIN**, **ACTIVE-PR**, **PARTIAL**, **PLANNED**, and **SUPERSEDED**.

## System boundary

`pg-llm-batch` is a Python package plus PostgreSQL schema and container assets. It can run standalone or be embedded. It owns bounded batch preparation, PostgreSQL persistence, validated provider Batch API access, durable lifecycle/checkpoint state, tenant/RLS controls, bounded reconciliation, tenant-qualified transient single-flight, bounded recovery evidence, bounded logical restore, and bounded restore-target cluster-identity comparison. It does not own host authentication/business authorization, infrastructure TLS, external secret-manager choice, global telemetry policy, backup/WAL infrastructure, connection provenance, or cross-system distributed transactions.

## Component contract

| Component | Protected-main responsibility | Prohibited authority |
| --- | --- | --- |
| `token_counter.py` | reviewed PostgreSQL tokenizer boundary | provider credentials, tenant authorization, provider I/O |
| `orchestrator.py` | deterministic bounded preparation and package persistence | provider protocol/retry policy |
| `batch_api_client.py` | validated bounded provider upload/create/poll/wait/cancel/retrieve | tenant authentication, scheduler ownership |
| `durable_client.py` | standalone and tenant-qualified lifecycle composition | authenticating/authorizing host tenants |
| `db.py` | schema application and parameterized durable reads/writes/RLS context | database-side provider networking |
| `checkpoint_store.py` | tenant-qualified checkpoint/CAS operations | distributed exactly-once claims |
| `reconciliation.py` | finite host-selected reconciliation | discovery and scheduling |
| `reconciliation_single_flight.py` | transient tenant-qualified PostgreSQL session advisory-lock exclusion | durable lease, scheduler, result application, terminal retirement, distributed exactly-once |
| `postgres_recovery_receipt.py` | deterministic bounded content-free receipt | backup/restore execution or operator authentication |
| `postgres_backup_evidence.py` | descriptor-pinned finite artifact hash/size evidence | backup execution or restorability proof |
| `postgres_schema_evidence.py` | finite packaged-schema hash/size evidence | SQL execution or live-cluster parity proof |
| `postgres_logical_restore.py` | bounded custom-format direct restore with caller-owned source trust, constrained libpq environment, transactional failure handling, and archive metadata verification | backup creation, target authentication, application readiness, PITR/RPO-RTO |
| `postgres_restore_target.py` | require distinct exact service names and distinct caller-owned PostgreSQL `system_identifier` values before a host treats targets as separate | opening connections, accepting DSNs/passwords, authenticating identity collection, executing restore, application/catalog/PITR/RPO-RTO proof |
| `config.py` | PostgreSQL-backed config/secret storage with optional Fernet and explicit compatibility mode | mandatory encryption, compatibility-row migration, rotation/recovery, external key custody |
| `observability.py` | opt-in bounded telemetry | global SDK/exporter/resource policy |
| `health.py` | redacted readiness aggregation | arbitrary diagnostic reflection |
| `cli.py` | standalone operator composition | higher-level workflow orchestration |

## Runtime architecture

### Batch preparation and provider I/O

Preparation resolves a supported package identity, reads eligible requests, counts tokens through `pg_tiktoken`, partitions under finite token/byte/record/provider limits, and commits package payload/file/line/request assignments atomically. Package payloads remain PostgreSQL-backed rather than package-owned local files.

Provider URLs and identifiers are untrusted until validated. Production destinations require the reviewed secure URL policy. Control responses and result/error files are consumed under finite decoded-byte budgets. Automatic retry stays limited to reviewed idempotent GET semantics; side-effecting POSTs remain single-attempt unless a separately reviewed provider contract changes that rule.

### Durable lifecycle tenancy

Standalone lifecycle state uses the explicit `standalone` scope and preserves the four-argument `DurableBatchAPIClient` recorder seam. Tenant-aware clients validate trusted host-selected `tenant_scope` before reservation, credential resolution, provider I/O, or lifecycle SQL. Durable tenant identity is `(tenant_scope, endpoint_alias, remote_batch_id)` and package reads/writes bind that scope using parameterized transaction-local `set_config` under forced RLS. `tenant_scope` is routing context, not authentication. `SUPERUSER`, `BYPASSRLS`, and arbitrary SQL are administrative escape hatches outside the tenant guarantee.

### Checkpoints and reconciliation

Checkpoint storage is tenant-qualified and compare-and-swap based. PostgreSQL transactionality does not extend to provider/network effects.

`reconcile_batch_candidates(...)` performs one finite host-selected reconciliation pass. Protected main also contains the tenant-qualified session advisory single-flight integrated through #191. That lock is session-lifetime transient state, not a scheduler, durable lease, result-application transaction, terminal-work-retirement authority, or distributed exactly-once mechanism. Durable discovery remains active work.

### PostgreSQL recovery

Protected main contains bounded receipt, backup-artifact, and packaged-schema evidence primitives. These do not execute backup/restore, establish provenance, prove live schema, or establish PITR/RPO/RTO/HA/DR.

Direct `pg_restore` execution is **IMPLEMENTED-ON-PROTECTED-MAIN** through merged #212. The executor accepts PostgreSQL custom-format random-access seek semantics and verifies archive metadata rather than requiring final descriptor EOF. Closed #209 remains historical defect evidence for the invalid EOF postcondition. The executor retains caller-owned source-superuser trust, constrained libpq environment, and single-transaction failure semantics; it does not provide `pg_dump`, target identity authentication, application/catalog readiness, WAL/PITR, or recovery-objective proof.

Restore-target cluster identity verification is also **IMPLEMENTED-ON-PROTECTED-MAIN** through merged #228. `postgres_restore_target.py` accepts exact live/restore libpq service names and exact `PostgresRestoreTargetIdentity` values; both names and both `pg_control_system().system_identifier` values must differ. Callers collect the identifiers from connections they already opened. The package does not open a connection, read `pg_service.conf`, accept a DSN/password/host/port, authenticate the collector or connection provenance, execute `pg_restore`, or prove post-restore schema/application readiness. Thus the seam rejects same-cluster aliases but is not end-to-end restore authorization.

Logical `pg_dump` remains active work. #296 remains an unshipped application-readiness candidate, and #341 remains the active owner of a permanent hosted live-PostgreSQL integration lane. Their branch-level evidence does not become protected-main truth until integration.

## Persistence, security, and privacy

Package-owned persisted payload/state is canonical and validated before downstream effects when correctness depends on it. New database objects use descriptive snake_case naming where applicable, parameterized SQL, synchronized schema copies, explicit durable identities, and documented migration/rollback boundaries.

Standalone config and secrets are PostgreSQL-backed. Fernet is optional on protected main. `SecretStore(require_encryption=False)` permits base64-obfuscated compatibility rows with `is_encrypted = FALSE`; callers may explicitly require Fernet. Mandatory encrypted-at-rest policy, migration of historical compatibility rows, key rotation/recovery, and external key custody are separate capabilities.

Authorized prompts, requests, JSONL, and provider results are not silently masked or truncated merely because they may contain PII. Such transformation changes token counts, replay, provider semantics, and business meaning. Host authentication/authorization, tenant selection, least-privilege identities, transport/storage controls, retention/deletion policy, and redacted operational evidence are the confidentiality boundaries. Any content transformation requires an explicit host/business policy with provenance and acceptance tests.

Errors, logs, telemetry, readiness, and review evidence omit DSNs, credentials, prompt/provider content, arbitrary SQL, untrusted identifiers, and dynamic lower-layer text where it is unnecessary. RLS remains defense in depth rather than authentication or SQL-injection prevention.

## Concurrency, testing, and release

Batch preparation and durable writes use PostgreSQL transactionality appropriate to their aggregate boundary. Session advisory locking is transient and must not be promoted to durable leasing. Recovery file inspection remains finite and fail-closed under mutation; a successful hash is evidence for the revalidated descriptor identity, not a lock on external storage.

Every defect follows realistic RED → minimum causal fix → exact-head GREEN. Repository evidence includes Python 3.10/3.12/3.14, exact owned production statement/branch coverage, public docstrings, lint/static checks, PostgreSQL integration for SQL/RLS/migration/concurrency behavior, package/container validation, migration rollback where applicable, security/SAST, locked packaging, release acceptance, SBOM/provenance, and artifact identity. Queued, skipped, cancelled, absent, stale, predecessor, synthetic-only, or infrastructure-failed evidence is not success.

A release originates only from an exact integrated protected head after all then-required quality, security, review, migration/recovery, packaging, provenance, and release gates pass. Version/CHANGELOG/package/tag/publication do not become authoritative until publication and artifact verification complete. Recovery evidence, logical restore execution, or `system_identifier` comparison alone does not make a release end-to-end recovery-ready.

## Documentation requirements

Canonical PRD/TRD/architecture/ADR/UML/ERD/security/operability/release/data-governance/traceability surfaces distinguish protected-main state from active work and avoid exact SHAs/run IDs. ADR 0016 records bounded restore-seek semantics. ADR 0022 records bounded restore-target name+cluster-identity separation. Broader direct-SQL, target-authentication, application-readiness, PITR, or recovery-objective changes require coordinated permanent documentation through their current owners.
