# pg-llm-batch Technical Requirements Document

- **Document status:** Proposed canonical authority on PR #93
- **Protected-main baseline:** `bf2cc2e140dc3ff4a56c3203f80f41bb9fed5d10`
- **Runtime language:** Python >= 3.10
- **Primary durable platform:** PostgreSQL with package/bundled extension requirements
- **External provider contract:** OpenAI-compatible Files/Batches HTTP API

## 1. Technical objective

The implementation must provide one bounded, composable path from PostgreSQL-backed LLM requests to provider batch jobs and back while keeping state authority, resource bounds, credentials, retries, telemetry, migrations, and evidence semantics explicit. It must remain independently deployable and embeddable without introducing a mandatory service mesh, gateway vendor, telemetry exporter, or ContextualWisdomLab-only runtime.

## 2. Protected-main component model

| Responsibility | Protected-main implementation | Authority |
| --- | --- | --- |
| token counting / batch accumulation | `pg_llm_batch/token_counter.py` | PostgreSQL tokenizer mapping + `pg_tiktoken` |
| transactional batch preparation | `pg_llm_batch/orchestrator.py` | PostgreSQL queue/batch/request/payload state |
| provider Files/Batches client | `pg_llm_batch/batch_api_client.py` | caller inputs + validated credential provider + provider response |
| durable provider lifecycle | `pg_llm_batch/durable_client.py`, `pg_llm_batch/db.py` | `llm_remote_batch_jobs` + observation sequence |
| config/secrets | `pg_llm_batch/config.py` | `com_config`, `com_secrets` |
| optional operation telemetry | `pg_llm_batch/observability.py` | host-owned OpenTelemetry API/SDK |
| schema/migrations available on main | `pg_llm_batch/schema.sql`, DB helpers | PostgreSQL |
| CLI | `pg_llm_batch/cli.py` | operator/caller |
| readiness | `pg_llm_batch/health.py`, `pg_llm_batch_health_check()` | current DB/component state |
| standalone deployment | `Dockerfile`, `docker/postgres/`, `docker-compose.yml` | deployment operator |

## 3. Data and persistence requirements

### TRD-D1 — Descriptive database objects

Package-owned database object names shall use descriptive snake_case and at least two words by default. The canonical protected-main schema includes `com_config`, `com_secrets`, `llm_queues`, `llm_batches`, `llm_batch_file_payloads`, `llm_batch_files`, `llm_requests`, `llm_jsonl_lines`, `llm_endpoints`, `llm_endpoint_models`, and `llm_remote_batch_jobs`.

### TRD-D2 — Relational integrity

Queue, batch, file, request, JSONL line, endpoint/model, and payload relationships shall use explicit relational keys/constraints where the schema declares a relationship. The documentation must not invent a foreign key between `llm_remote_batch_jobs.endpoint_alias` and `llm_endpoints.endpoint_alias`; protected main deliberately persists the lifecycle alias as validated text without such a FK.

### TRD-D3 — Disk-free payload path

The package-owned preparation path shall persist JSONL data in PostgreSQL and reconstruct virtual payloads without requiring package-owned temporary files.

### TRD-D4 — Durable observation ordering

`DurableBatchAPIClient` shall reserve a positive database-owned observation order before provider I/O for lifecycle operations it persists. Failed reservations must fail before provider effects; persistence failures after a successful provider operation must retain bounded recovery evidence.

### TRD-D5 — Current-main versus active migration truth

Checkpoint, checkpoint-audit, snapshot-manifest, and tenant-RLS schema described by open PRs shall remain `ACTIVE-PR` until protected integration. ERD and operator documents must keep those entities separate from protected-main tables.

## 4. Provider HTTP requirements

### TRD-H1 — Credential-bearing destination validation

Gateway base URLs shall be validated before use. Protected main requires HTTP(S) syntax with a hostname, rejects user information/query/fragment/invalid port/ambiguous whitespace or backslashes, and requires HTTPS for non-loopback destinations.

### TRD-H2 — Provider identifier validation

Batch/file resource identifiers used in URL path segments shall use the reviewed bounded ASCII grammar and length. Batch endpoint paths shall reject traversal, query, fragment, percent-escape ambiguity, empty segments, and unsupported syntax.

### TRD-H3 — Time bounds

Every provider request shall operate under a finite configurable timeout. Waiting for a batch terminal state shall also be bounded by caller-configurable timeout and polling parameters.

### TRD-H4 — Control-plane memory bound

Files/Batches JSON control responses shall be streamed under `DEFAULT_MAX_CONTROL_RESPONSE_BYTES` (1 MiB on the protected-main baseline), decoded as strict UTF-8, and parsed as the required JSON shape without falling back to unbounded `response.text()`/`response.json()` behavior.

### TRD-H5 — Provider-file memory bound

Result/error files shall be streamed in bounded chunks under `DEFAULT_MAX_DOWNLOAD_BYTES` (128 MiB on protected main by default). The decoded-byte bound applies before complete JSONL materialization. `ACTIVE-PR` #58 further replaces aggregate record materialization with incremental record delivery.

### TRD-H6 — Replay boundary

Automatic retries shall not duplicate side-effecting provider operations by default. Protected main retries only the reviewed idempotent GET status set `{408, 429, 502, 503, 504}` plus reviewed acquisition transport failures within finite attempts. POST upload/create/cancel operations remain single-attempt. `ACTIVE-PR` #71 changes this target by adding HTTP 425 and explicitly classifying TLS/certificate/fingerprint failures as permanent; documentation must not retroactively claim that target is already on main.

### TRD-H7 — Retry-After

A valid bounded `Retry-After` delta-seconds or HTTP-date may guide a GET retry. Invalid guidance falls back to bounded jitter; syntactically valid guidance above the configured maximum shall not create an unbounded sleep.

## 5. Configuration and credential requirements

### TRD-C1 — Bootstrap transport

The protected-main design uses environment variables only for bootstrap transport such as PostgreSQL DSN and optional Fernet key where documented. Operational provider configuration and API keys live behind database/injected seams.

### TRD-C2 — Pluggable credential provider

`BatchAPIClient` shall accept a caller-supplied credential resolver. The package-provided resolver obtains gateway URL from configuration and endpoint-scoped API key from `SecretStore`.

### TRD-C3 — Secret-at-rest behavior

`SecretStore` supports Fernet encryption when configured. Absence of cryptography/key support must remain explicit and must not be represented as equivalent confidentiality. `ACTIVE-PR` #85 removes secret values from process argv; protected-main CLI behavior remains the baseline until that PR integrates.

### TRD-C4 — Typed configuration target

Protected main has database-backed typed defaults but open #86 owns stronger canonical write/collection-shape/mutable-cache behavior. The technical target is deterministic read-after-write/reload semantics without caller mutation of package-owned state.

## 6. Tenancy and authorization requirements

### TRD-A1 — Current state

Protected-main `llm_remote_batch_jobs` is keyed by endpoint alias + remote batch ID and does not yet persist package-owned tenant scope.

### TRD-A2 — Accepted active target

`ACTIVE-PR` #53 introduces trusted host-selected tenant scope, tenant-qualified durable lifecycle state, PostgreSQL RLS, and `NOSUPERUSER NOBYPASSRLS` application-role expectations. Provider metadata, aliases, IDs, payloads, and transport headers must never select tenant scope.

### TRD-A3 — Host authorization remains host-owned

Even with package RLS, mapping an authenticated user/workload to the correct trusted tenant scope is an embedding-host responsibility. A database custom setting is not by itself an authentication mechanism.

## 7. Observability requirements

### TRD-O1 — Optional dependency

Base package operation shall not require a configured OpenTelemetry SDK/exporter. Hosts may opt into `OpenTelemetryBatchAPIClient`.

### TRD-O2 — Low-cardinality/privacy boundary

Package-owned telemetry shall not export prompts, provider bodies, credentials, DSNs, endpoint aliases, remote resource identifiers, tenant identifiers, or dynamic caller/provider exception-class names as custom attributes. Operation/error vocabularies must stay finite and documented.

### TRD-O3 — Observer failure isolation

Ordinary telemetry failures and telemetry-originated cancellation must not change provider-call results or replace the application exception. Process-level control-flow exceptions not explicitly classified for isolation must not be silently swallowed.

## 8. Readiness and deployment requirements

### TRD-R1 — Readiness decision

Protected main treats database, `pg_tiktoken`, and `com_config` as required readiness components and exposes a CLI health command plus `/healthz`. Current behavior includes component details and a simple HTTP server; #70 owns stronger redaction, concurrency, statement/read timeout, and listener defaults.

### TRD-R2 — Standalone Compose

The bundled Compose file provides PostgreSQL and component services and uses bootstrap DSN transport. Protected main publishes 5432/8080 without an explicit host IP; #91 is the `ACTIVE-PR` security target for loopback-only standalone publication.

### TRD-R3 — Embedded deployment

Embedding services may import the package directly and own ingress, service identity, DSN acquisition, tenant authorization, external secret management, telemetry resource/export configuration, and higher-level transaction boundaries.

## 9. Reliability and recovery requirements

### TRD-REL1 — Idempotent local preparation

Batch preparation and persistent identities shall support safe retry/restart behavior rather than silently appending or duplicating prepared artifacts for an already-established batch identity.

### TRD-REL2 — Lifecycle reconciliation

Durable lifecycle errors shall retain enough bounded phase/operation/order/validated-identity information for reconciliation without placing provider-controlled bodies into exported diagnostics.

### TRD-REL3 — Checkpoint target

`ACTIVE-PR` #59/#60 defines resumable prefix evidence and durable compare-and-swap checkpoint storage. The package shall not call that distributed exactly-once delivery; external side effects across systems require host idempotency/outbox/reconciliation.

### TRD-REL4 — Audit target

`ACTIVE-PR` #79/#83/#84 defines append-only acceptance evidence, stable pagination, and snapshot manifests. Audit evidence does not make a PostgreSQL owner/superuser cryptographically unable to modify data; that residual boundary must remain explicit.

## 10. CI, evidence, and review requirements

### TRD-E1 — Deterministic quality gate

Repository CI shall cover supported Python versions, non-integration tests, compile, Ruff, 100% owned production statement/branch coverage, 100% public docstrings, lock freshness, package build, Compose validation, and component/PostgreSQL image build as applicable to the live workflow.

### TRD-E2 — Exact source identity target

Protected-main CI currently uses default checkout behavior for `pull_request`; GitHub documents that this checks out the generated merge ref. `ACTIVE-PR` #88 binds checkout/verification to `github.event.pull_request.head.sha`. Until integrated, generated-merge CI is useful compatibility evidence but must not be mislabeled exact source-head proof.

### TRD-E3 — Evidence-class separation

The following are distinct and non-substitutable: contributor/source head, PR base snapshot, live base ref tip, synthetic merge commit, commit status/check run, workflow checked-out commit, formal review, unresolved thread state, independent approval, branch protection/ruleset, security finding, release artifact/provenance evidence.

### TRD-E4 — Independent review

Where repository/CWL policy requires qualifying independent non-author approval, no author comment, bot status, synthetic text, reaction, old-head review, or COMMENTED review is equivalent to that approval.

## 11. Packaging and release requirements

### TRD-PKG1 — Package metadata

Protected main builds `pg-llm-batch` version `0.1.0`, Python >=3.10, Apache-2.0, with `LICENSE` and `NOTICE` included and a console script `pg-llm-batch`.

### TRD-PKG2 — Reproducibility target

`ACTIVE-PR` #57 owns descriptor-pinned clean-archive reproducibility evidence. Publication/attestation authority remains separate from read-only verification.

### TRD-PKG3 — Protected integration only

Version bump, release creation, publication, and provenance acceptance shall use an exact integrated protected head after all required checks, independent review, security, packaging, migration/recovery, and operational gates are satisfied.

## 12. Documentation requirements

The repository shall keep a canonical PRD, TRD, Architecture, UML, ERD, Threat Model, Test Strategy, Operability guide, ADR index, automation-governance ADRs, and Traceability matrix. Each must distinguish `IMPLEMENTED-ON-PROTECTED-MAIN` from `ACTIVE-PR` and must be tested for presence/core authority terms.

## 13. Authoritative references

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://www.rfc-editor.org/rfc/rfc9110.html

GitHub. (2026). *Events that trigger workflows*. GitHub Docs. https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Row security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html
