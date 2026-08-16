# Technical Requirements Document

## Document authority

This TRD defines technical invariants for `pg-llm-batch`. It distinguishes protected-main behavior from work that is only present in an active pull request. The repository's live code, schema, tests, ruleset, and exact-head evidence remain stronger authority than historical branches, stale PR prose, predecessor checks, or generated merge commits.

Status vocabulary is shared with the PRD: **IMPLEMENTED-ON-PROTECTED-MAIN**, **ACTIVE-PR**, **PARTIAL**, **PLANNED**, and **SUPERSEDED**.

## System boundary

`pg-llm-batch` is a Python package plus PostgreSQL schema and container assets. It may run standalone or be embedded by another service. The package owns batch preparation, package persistence, validated provider Batch API access, durable lifecycle projection, resumable checkpoint storage, bounded reconciliation primitives, and bounded content-free PostgreSQL recovery-evidence primitives. It does not own host authentication, business authorization, ingress/WAF, infrastructure TLS policy, external secret-manager choice, global OpenTelemetry configuration, backup-storage infrastructure, WAL/archive infrastructure, or a cross-system distributed transaction.

## Component contract

| Component | Protected-main responsibility | Prohibited authority |
| --- | --- | --- |
| `token_counter.py` | resolve reviewed tokenizer metadata and call `pg_tiktoken` for token accounting | provider credentials, tenant authorization, provider I/O |
| `orchestrator.py` | select queued requests, partition under limits, persist package payload/file/line/request assignments | provider protocol and retry policy |
| `batch_api_client.py` | validate provider destination and remote identifiers; upload/create/poll/wait/cancel/retrieve under finite budgets | tenant authentication, scheduler ownership |
| `durable_client.py` | compose provider operations with durable lifecycle ordering/persistence; preserve `DurableBatchAPIClient` source compatibility, its four-argument `LifecycleRecorder(postgres_dsn, endpoint_alias, provider_batch, observation_order)` seam, and default `standalone` database scope; provide a distinct tenant-qualified recorder seam | authenticating or authorizing host tenants, deriving tenant authority from provider data |
| `db.py` | schema application and parameterized persistence/read helpers, including tenant-qualified lifecycle context, conflict identity, and exact-row lookup | database-side provider networking, authenticating tenant callers |
| `checkpoint_store.py` | tenant-qualified PostgreSQL checkpoint/CAS operations and conflict semantics | distributed exactly-once claims |
| `reconciliation.py` | finite host-selected polling/retrieval pass using the existing validated client surface | candidate discovery, scheduling, cross-process leasing |
| `postgres_recovery_receipt.py` | encode/decode one deterministic bounded content-free PostgreSQL recovery evidence receipt | proving backup success/restorability, authenticating operators, carrying DSNs/credentials/business content |
| `postgres_backup_evidence.py` | derive SHA-256 and byte-size evidence from one private regular backup artifact through descriptor-pinned no-follow traversal and finite work | executing `pg_dump`/`pg_restore`, persisting backup bytes, proving restore semantics |
| `postgres_schema_evidence.py` | derive SHA-256 and byte-size evidence from the exact distributed `pg_llm_batch/schema.sql` resource under a finite package-owned budget | executing SQL, proving live-cluster parity or migration currency |
| `config.py` | PostgreSQL-backed configuration and encrypted secret storage for standalone composition | prescribing an embedding host's external secret manager |
| `observability.py` | opt-in bounded traces/metrics around reviewed operations | configuring global SDK/exporter/resource policy |
| `health.py` | readiness aggregation and redacted public health response | general-purpose web serving or arbitrary diagnostic reflection |
| `cli.py` | standalone operator composition and bounded input surfaces | higher-level workflow orchestration |

The protected-main validation authority for the `durable_client.py` compatibility row is `pg_llm_batch/durable_client.py`, `tests/test_tenant_durable_client.py`, and `tests/test_tenant_lifecycle_persistence.py`: the tests prove construction-time tenant rejection before downstream effects, exact four-argument standalone recorder invocation, explicit `standalone` persistence/read delegation, and tenant-qualified lifecycle persistence/read identities.

The protected-main validation authority for recovery evidence is the three recovery modules plus their focused test suites. Historical merged PRs #205, #206, and #207 are integration evidence, not runtime authority. `docs/TRACEABILITY.md` remains the canonical status map for the distinction between integrated evidence primitives and active backup/restore execution candidates.

## Runtime architecture

### Batch preparation

1. Resolve a supported package batch identity.
2. Read eligible unassigned requests from PostgreSQL.
3. Count model tokens through the reviewed PostgreSQL tokenizer boundary.
4. Partition requests in memory under explicit batch token, byte, record, and provider limits.
5. Under one package preparation transaction, persist virtual payloads, batch-file rows, JSONL line rows, request assignments, and aggregate totals in deterministic order.
6. On failure before commit, roll back the package preparation transaction rather than exposing a partially committed preparation from that invocation.

Package-generated provider payloads are represented by `memory://<file_id>` references and are reconstructed from PostgreSQL rather than written to a package-owned local payload file.

### Provider I/O

Provider gateway URLs and endpoint aliases are configuration inputs but are untrusted until validated by the applicable package boundary. Production gateway destinations require HTTPS; only explicitly reviewed loopback development HTTP destinations are accepted. Userinfo, query, fragment, whitespace, malformed port, or other forbidden URL forms must fail before credentials are used.

Control-plane responses are consumed through a finite decoded-byte budget and strict UTF-8/JSON parsing. Provider output/error files are streamed in finite chunks with an independent decoded-byte ceiling before JSONL parsing. The client must fail closed when an adapter cannot provide the bounded streaming interface required by the operation.

Automatic provider retry is limited to reviewed idempotent GET operations and the exact default status set `{408, 425, 429, 502, 503, 504}`. TLS handshake, certificate, and fingerprint failures are not automatically retried. Upload/create/cancel POST operations remain single-attempt unless a separately reviewed provider-specific contract is introduced.

### Durable lifecycle tenancy

Standalone lifecycle data uses the exact `standalone` tenant scope. `DurableBatchAPIClient` preserves its original four-argument lifecycle-recorder interface `(postgres_dsn, endpoint_alias, provider_batch, observation_order)`; its default persistence path and `get_remote_batch_state(...)` compatibility helper resolve through the explicit `standalone` scope. Tenant-aware hosts instead use `TenantDurableBatchAPIClient` with a distinct tenant-qualified recorder seam so tenant identity cannot be silently dropped.

A tenant-aware client validates the trusted host-selected `tenant_scope` synchronously during construction, before any observation reservation, credential-provider lookup, provider I/O, or lifecycle database I/O can occur. Provider metadata, request payloads, model output, transport headers, endpoint aliases, provider resource identifiers, and credential data never choose tenant authority. Credential resolution remains a separate deployment/host concern: ordering tenant validation before it does not make the credential store tenant-keyed.

The durable lifecycle identity is:

```text
(tenant_scope, endpoint_alias, remote_batch_id)
```

Every tenant-aware lifecycle persistence conflict target and exact-row lookup includes the full identity. The protected schema's lifecycle operational status index begins with `tenant_scope`, and package reads/writes bind the validated scope with parameterized transaction-local `set_config`. The schema enables and forces PostgreSQL row-level security for tenant-qualified lifecycle state. Production application roles must be `NOSUPERUSER NOBYPASSRLS`. A role that can execute arbitrary SQL can choose arbitrary custom setting values; therefore generic arbitrary SQL access is explicitly outside the package isolation guarantee.

These invariants are deterministically verified on protected main: `tests/test_tenant_durable_client.py` proves malformed scope fails before reservation or credentials and proves the unchanged four-argument standalone recorder seam; `tests/test_tenant_lifecycle_persistence.py` proves malformed scope fails before database access, the upsert conflict target is `(tenant_scope, endpoint_alias, remote_batch_id)`, exact reads bind the same full identity, and standalone helpers delegate to `standalone`; `pg_llm_batch/schema.sql` supplies the tenant-qualified unique constraint, forced RLS policy, and `idx_llm_remote_batch_jobs_tenant_status_observed` index. `docs/remote-batch-lifecycle.md`, ADR 0002, and `docs/doctoring/tenant-scoped-lifecycle.md` document the same migration, direct-SQL/RLS, role, and rollback boundaries.

### Durable result checkpoints

Protected main contains tenant-qualified durable result checkpoint storage with compare-and-swap/conflict semantics. The checkpoint store can participate in a caller-owned PostgreSQL transaction where the caller's durable result application is in the same database transaction. The mere existence of this store does not prove exactly-once application across provider/network/database boundaries.

Checkpoint counters, offsets, and identities must validate before mutation. Conflicting writes fail explicitly rather than silently overwriting a newer checkpoint. Rollback/recovery tests and schema parity are part of the storage contract.

### Reconciliation

Protected main supplies a scheduler-independent `reconcile_batch_candidates(...)` primitive. A host supplies candidate identities and a finite `max_jobs` budget. The primitive validates candidates, bounds scanning/work, polls through the validated provider client, retrieves completed jobs through that same client, and returns payload-free finite outcome/error categories.

The host still owns candidate discovery, tenant authorization, scheduling, and cross-process concurrency. Durable candidate discovery and tenant-qualified advisory single-flight are **ACTIVE-PR** surfaces; neither is treated as shipped until protected-main integration. Package-owned autonomous scheduling, crash/restart completion semantics, terminal-work retirement after durable result application, and an end-to-end exactly-once worker remain **PARTIAL** or **PLANNED** capabilities.

### PostgreSQL recovery evidence

Protected main supplies three deliberately non-executing recovery-evidence primitives.

1. `PostgresRecoveryReceipt` binds exact built-in primitive metadata for package version, source commit, PostgreSQL major, packaged-schema SHA-256, reviewed backup-method vocabulary (`logical`, `physical`, or `pitr`), backup artifact SHA-256/size, and bounded timestamps. Its JSON representation is deterministic and size-bounded, rejects duplicate/unknown fields and hostile subclasses, and maps ordinary malformed input/decoder failures to fixed content-free diagnostics.
2. `inspect_postgres_backup_artifact(...)` traverses path components through pinned directory descriptors with no-follow semantics, rejects `..`, symlinked parents/final components, non-regular/empty/oversized files and unsafe link counts/permissions as defined by the implementation contract, hashes under an explicit finite maximum-size work budget, bounds each read request by remaining budget, compares descriptor identity/metadata before and after hashing, and treats cleanup failures as bounded evidence without masking an already-selected primary error.
3. `inspect_postgres_schema()` streams the exact distributed `pg_llm_batch/schema.sql` resource through SHA-256 under a finite package-owned work budget and returns only SHA-256 plus byte size. Missing, unreadable, empty, oversized, malformed-chunk, hostile-subclass, or cleanup-failing resources fail closed through fixed content-free diagnostics.

These primitives do not execute SQL or database mutation. They do not prove the backup command succeeded, prove backup provenance beyond caller-controlled receipt fields, prove restorability, prove a live database matches the packaged schema, provide target isolation, manage keys/secrets, manage physical/WAL/PITR infrastructure, or establish RPO/RTO/HA/DR/compliance. Those are separate acceptance domains.

Logical `pg_dump` execution in #208 remains **ACTIVE-PR**. Direct `pg_restore` execution is also **ACTIVE-PR**, but only Draft #212 is the current successor. Predecessor #209 is not a merge path: its EOF-consumption postcondition conflicts with seekable PostgreSQL custom archives and can report failure after `--single-transaction` has already committed. Until integration, no protected-main technical contract may rely on those executors. The #212 successor additionally requires permanent operator/architecture/ADR/doctoring/CHANGELOG coverage for caller-owned source-superuser trust, the non-authorizing service selector, permitted inherited libpq variables, single-transaction rollback behavior, target isolation, metadata-fingerprint verification, and post-restore acceptance before it may be represented as shipped.

## Persistence requirements

### Naming and schema ownership

New package-owned database objects use descriptive two-or-more-word `snake_case` names where applicable. SQL is parameterized; identifiers are not constructed from unvalidated user/provider text. Packaged schema and Docker initialization copies that represent the same contract must remain synchronized by regression tests.

### Migration behavior

Migrations must have an explicit compatibility and rollback boundary. Tenant migrations preserve legacy data under `standalone`, avoid a committed intermediate RLS-bypass state, restore forced RLS atomically, and remain idempotent where documented. Existing-volume retirement of legacy `http` / `pg_cron` authority is **ACTIVE-PR** and may not be described as shipped merely because fresh initialization no longer depends on SQL-side provider networking.

### Data integrity

Package-owned persisted virtual JSONL is canonical state, not a best-effort cache. Malformed shape, line count, framing, duplicate JSON members, non-finite numeric forms, or invalid record type fail closed through bounded package errors. Local payload integrity validation occurs before provider credentials/provider I/O where the provider effect relies on that payload.

Durable provider/resource identifiers and tenant identities are validated before they become persistence or authorization inputs. Database/query failures must not be silently reclassified as an authoritative no-row result when correctness depends on distinguishing those cases.

Recovery evidence is identity/integrity metadata, not a second persistence authority. The package does not own backup storage, replica lifecycle, object-store retention, WAL archives, encryption-at-rest infrastructure, or backup deletion merely because it can hash an operator-selected artifact. Operators/deployments must keep those responsibilities explicit.

## Security and privacy requirements

### Secrets

Standalone provider configuration and encrypted secrets are PostgreSQL-backed. Environment variables are limited to explicitly documented bootstrap transport such as the database DSN and optional encryption key. CLI secret entry uses no-echo prompting or bounded standard input rather than plaintext process arguments. Embedding hosts may supply another credential provider through the supported seam.

Recovery evidence must not carry DSNs, passwords, Fernet keys, prompts/results, ciphertext, arbitrary SQL, provider payloads, paths where not required by the callable interface, dynamic exception names, or reflected lower-layer diagnostics. A future backup/restore executor must isolate credentials from process arguments and ambient environment according to its separately reviewed contract.

### Authorized content fidelity

The package does not gain authority to mask, tokenize away, truncate for privacy, or otherwise alter an authorized prompt, request, JSONL record, or provider result merely because the content may contain PII. Silent transformation would change token counts, provider semantics, persisted evidence, replay behavior, and downstream business meaning. Serialization, token accounting, persistence, upload, and retrieval paths implemented on protected main therefore preserve authorized business content unless an explicit reviewed feature contract says otherwise. The same content-fidelity invariant constrains any result-application path that exists, but end-to-end result application remains **PARTIAL** under FR-4 and `docs/TRACEABILITY.md`; PR #194 is an **ACTIVE-PR** transaction-seam candidate, not protected-main proof of a completed result-application capability.

Confidentiality for content-bearing data is enforced through boundary controls rather than a blanket masking default: the embedding host authenticates and authorizes the caller and selects tenant scope; package/database/service identities remain least-privilege; and transport uses the reviewed secure destination policy. Protected main does not define a universal business-data retention duration or a general destructive deletion workflow. The embedding host owns business purpose, retention period, deletion authorization/trigger, and evidence that its policy was executed; the deployment owner separately owns PostgreSQL backup/replica, log/telemetry, and infrastructure retention/deletion controls; provider-side retention/deletion remains a provider/account-policy responsibility unless an explicit reviewed package adapter contract implements and verifies it. Package-owned errors, logs, telemetry, readiness, CI/review evidence, and other operational surfaces omit content-bearing values. A host that intentionally transforms content must do so through an explicit business-policy boundary with provenance and acceptance tests. Redacted operational evidence must never be represented as proof that persisted or provider-bound business content was masked or deleted.

### Diagnostic confidentiality

Errors, logs, telemetry, check evidence, and public readiness must avoid DSNs, credentials, prompts, provider bodies, arbitrary SQL/provider exception text, unvalidated identifiers, and dynamic exception-class names where those values are not required for operation. Failure categories intended for public/operational evidence use bounded vocabularies.

### Tenant boundary

RLS augments a trusted host authorization boundary; it is not itself authentication, a credential, or SQL-injection prevention. Administrative database identities are outside the ordinary tenant guarantee. Pooling code must not leak transaction-local tenant context between logical operations.

### Provider boundary

Provider URLs, statuses, IDs, headers, JSON, JSONL, retry guidance, and metadata are untrusted external input. Validation occurs before the downstream effect that relies on that value. Model/provider output never grants tenant, endpoint, credential, or filesystem authority.

### Recovery authority boundary

A backup artifact, receipt, service selector, schema hash, or backup method string is not authorization to read, write, restore, or replace a database. Authentication, authorization, target isolation, backup custody, key custody, destructive-operation approval, and recovery-objective ownership remain external until a separately integrated contract explicitly supplies and verifies them. Recovery evidence must never be used to infer those authorities.

## Observability requirements

OpenTelemetry support is opt-in. Base installations must not require OpenTelemetry packages solely to use normal batch functionality. Operation names, outcomes, and error categories are finite. Telemetry attributes exclude endpoint aliases, provider URLs, resource identifiers, credentials, metadata, prompts, and provider response bodies.

A first-class packaging extra for OpenTelemetry is **ACTIVE-PR** until its exact generated dependency lock is committed normally, temporary materialization machinery is removed, and final package/install/release gates succeed.

## Health and operability

Readiness covers the required PostgreSQL/tokenizer/configuration boundary and returns redacted public evidence. A failing dependency must not cause arbitrary lower-layer text to be reflected to a caller. Docker/container health and package health semantics must remain aligned.

Operational migrations require backup/preflight/acceptance/recovery documentation before release. A recovery instruction must preserve package and operator-owned state; destructive `CASCADE`, hidden history rewrite, or deletion of unknown operator objects is not an acceptable shortcut.

A recovery drill must distinguish artifact identity from restore acceptance. At minimum, acceptance criteria for a future end-to-end logical restore must address exact schema/package identity, required schema/RLS/constraint/extension behavior, migration compatibility, intended target isolation, credential/key availability, and rollback/recovery behavior. Physical/WAL/PITR drills additionally require their own timeline/target and infrastructure acceptance criteria. No repository evidence should claim universal RPO/RTO/HA/DR without an explicit measured deployment objective.

## Concurrency requirements

Batch preparation uses database coordination/transactionality appropriate to its package-owned state. Durable lifecycle writes use explicit ordering/conflict semantics. Any cross-process reconciliation exclusion must be tenant-qualified, non-blocking or finitely bounded, exception-safe, and clear about whether it is transient session state or durable lease state. Session advisory locking must never be promoted into a durable lease or distributed exactly-once claim.

Recovery-evidence file inspection must remain finite and fail closed under concurrent mutation. A successful hash/size result is valid only for the descriptor identity/metadata contract that was revalidated by the implementation; it is not a lock or lease over external backup infrastructure.

## Testing requirements

Every source defect follows realistic RED → narrow fix → GREEN → focused/full validation. Required repository evidence includes:

- Python 3.10, 3.12, and 3.14 where configured;
- exact 100% owned production statement and branch coverage;
- public docstring coverage;
- lint/static checks;
- realistic PostgreSQL integration for SQL/RLS/migration/concurrency behavior;
- package and container installation/health validation;
- migration idempotency and rollback/recovery coverage where applicable;
- recovery-evidence tests for exact primitive types, duplicate/unknown metadata, finite work, descriptor/path boundaries, concurrent mutation, cleanup failure, and content-free diagnostics;
- confidentiality regressions that inspect full exception/traceback surfaces when relevant;
- security scanning and SAST;
- dependency-lock and packaging reproducibility;
- release acceptance, artifact identity, SBOM, and provenance evidence required by the live repository contract.

Queued, pending, skipped, cancelled, absent, neutral, stale, predecessor-head, synthetic-merge-only, status-only, infrastructure-failed, or rate-limited evidence is not exact-head success.

## Release requirements

A release may originate only from the exact integrated protected head after all live required quality, security, review, migration, rollback/recovery, operational, packaging, provenance, and release-acceptance gates are terminal-success. Versioning and CHANGELOG updates are followed by publication and artifact verification. Repository control evidence may support SOC 2 / CSAP readiness but must not be represented as certification.

The presence of recovery-evidence primitives does not make a release recovery-ready for a deployment. A release or operator contract that claims restore/PITR/RPO/RTO/HA/DR readiness must cite the exact integrated executor/drill/acceptance evidence for that deployment objective rather than extrapolating from hash/receipt modules.

## Documentation requirements

Canonical product/technical/architecture/ADR/UML/ERD/security/operability/release/data-governance/traceability documents must distinguish shipped protected-main state from active or planned work. Durable documents should describe contracts rather than transient check-run IDs. When an active capability merges, the canonical graph is updated in the same governance model rather than relying on stale PR body claims.

Direct-SQL or rollback authority introduced by a future backup/restore executor requires coordinated permanent README, operator, architecture, ADR (or explicit accepted amendment/no-new-decision rationale), doctoring/reference, and CHANGELOG coverage. Active PR source may document its own callable boundary, but canonical docs must not represent it as shipped before integration.
