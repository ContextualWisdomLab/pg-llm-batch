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

### TRD-D6 — Data classification and lifecycle authority

The canonical engineering authority for sensitive content, credentials, provider disclosure, telemetry, and operational evidence is `docs/DATA_GOVERNANCE.md`. New persisted fields or emitted logs/metrics/traces shall receive an explicit **data classification** before release. Purpose/business authorization, retention, erasure/export, backup expiry, and data residency remain **host-owned** unless an accepted package ADR and implementation explicitly move that authority. Package-side redaction, bounded telemetry, or tenant RLS must not be treated as substitutes for host authorization.

### TRD-D7 — Structured exception evidence ownership

`PgLlmBatchError.details` and `GatewayError.response_data` are **structured exception evidence**, not persistence or audit records. **ACTIVE-PR #105** requires a **constructor-time shallow snapshot** of the **outer caller-owned mapping** so later caller-side additions, removals, or replacements cannot rewrite the package-owned outer evidence after construction.

The snapshot must remain bounded and compatibility-preserving: **nested mutable values** remain shared, and direct mutation of the exception-owned public mapping remains possible. The live exception object is therefore not immutable and **not a durable audit record**. Durable audit evidence requires an explicitly serialized, bounded, authorized, and retained record outside the live exception object. This requirement remains ACTIVE-PR until #105 or a reviewed successor reaches protected main and receives fresh validation.

### TRD-D8 — Endpoint-qualified tokenizer metadata

Issue #108 is a PLANNED data-integrity follow-up for model metadata authority. When multiple provider endpoints advertise the same `model_id`, tokenizer selection must be **endpoint-qualified tokenizer** metadata rather than an ambiguous model-only lookup. The implementation must bind tokenizer resolution to the validated endpoint/model identity, fail closed on missing or conflicting metadata, preserve backwards compatibility only where one unambiguous mapping exists, and prove cross-endpoint isolation with realistic PostgreSQL tests before release.

## 4. Provider HTTP requirements

### TRD-H1 — Credential-bearing destination validation

Gateway base URLs shall be validated before credential use. On protected main, `_normalize_gateway_url()` first **stringifies** the configured value with `str(value)` and **strips surrounding whitespace** before parsing; it then rejects an empty normalized value, remaining whitespace/control characters or backslashes, user information, query/fragment, invalid ports, and unsecured non-loopback HTTP. That normalization means protected main can accept a stringifiable non-string value or an otherwise valid URL surrounded by whitespace, so it is not an exact caller-authority boundary. `ACTIVE-PR` #71 tightens the target: the gateway value must already be an **exact string**; stringifiable non-string inputs and leading/trailing whitespace, controls, or backslashes fail **before secret lookup**; and only an accepted trailing path **slash** may be normalized **after exact validation**. The exact-input behavior remains ACTIVE-PR until protected integration and fresh validation.

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

### TRD-H8 — Provider-error confidentiality overlay

`ACTIVE-PR` #71 also owns the current provider-error confidentiality target. For governed Files/Batches operations, a non-success HTTP status is classified from the status before provider-controlled body parsing, so an error body is not required to decide the bounded exported error category. A malformed successful UTF-8 or JSON response must fail with fixed bounded diagnostics and must not retain provider bytes/text or decoder/parser exceptions through exported exception `cause` or `context`. These status-first and malformed-success protections remain `ACTIVE-PR` until protected integration and fresh validation.

### TRD-H9 — Retire the legacy direct-SQL provider client

`ACTIVE-PR` #101 decommissions the bundled `pg_cron` + `pgsql-http` provider retriever rather than attempting to secure a second network/credential implementation inside PostgreSQL. The legacy path can decode only the weaker base64-obfuscated secret representation and treats a **local batch UUID** as if it were a **provider remote batch** identifier even though protected main has no reviewed local-to-remote identity binding for that operation. The cleanup must unschedule only the exact legacy job identity, remove its helper functions, retain historical retrieval logs, and never create credential-bearing database HTTP. Provider authority remains `BatchAPIClient` / `DurableBatchAPIClient`. This is ACTIVE-PR until #101 integrates and receives fresh protected-main acceptance.

### TRD-H10 — Strict provider progress/control values

Issue #98 is a PLANNED follow-up to the overlapping #71 provider-control surface. Successful provider JSON must not allow malformed `request_counts`, boolean/negative/string counters, `NaN`, `Infinity`, or other non-finite control values to escape as raw runtime exceptions or non-standard structured output. The accepted shape/counter invariants must fail closed through bounded package diagnostics while preserving the existing control-response size, strict UTF-8, retry/replay, and provider-error confidentiality contracts.

## 5. Configuration and credential requirements

### TRD-C1 — Bootstrap transport

The protected-main design uses environment variables only for bootstrap transport such as PostgreSQL DSN and optional Fernet key where documented. Operational provider configuration and API keys live behind database/injected seams. `ACTIVE-PR` #89 makes the caller-selected bootstrap authority explicit: an **explicit Postgres DSN** and an **explicit Fernet bootstrap key** must each already be an **exact string** when supplied. A non-string explicit value fails at the bootstrap boundary before **environment fallback**; only an omitted argument may consult the corresponding bootstrap environment variable. The explicit DSN must also be nonblank, while an explicit empty Fernet string intentionally suppresses ambient decryption authority. These exact-string/type and source-precedence rules remain ACTIVE-PR until #89 or a successor reaches protected main.

### TRD-C2 — Pluggable credential provider

`BatchAPIClient` shall accept a caller-supplied credential resolver. The package-provided resolver obtains gateway URL from configuration and endpoint-scoped API key from `SecretStore`.

### TRD-C3 — Secret-at-rest behavior

`SecretStore` supports Fernet encryption when configured. Absence of cryptography/key support must remain explicit and must not be represented as equivalent confidentiality. `ACTIVE-PR` #85 removes secret values from process argv; protected-main CLI behavior remains the baseline until that PR integrates.

### TRD-C4 — Typed configuration target

Protected main has database-backed typed defaults but open #86 owns stronger canonical write/collection-shape/mutable-cache behavior. The technical target is deterministic read-after-write/reload semantics without caller mutation of package-owned state.

### TRD-C5 — Stored-secret decoding/decryption overlay

`ACTIVE-PR` #87 owns the current fail-closed stored-secret target. The no-key local/development path must accept only strict Base64 alphabet/padding and strict UTF-8; malformed persisted data must produce a bounded `ConfigError` rather than leaking raw stored content. When Fernet is configured, a wrong Fernet key or invalid encrypted value must also become a bounded `ConfigError` without retaining ciphertext or the underlying cryptography exception through exported exception cause/context. Base64 without a Fernet key remains obfuscation, not encryption. These protections are not protected-main guarantees until #87 or a successor integrates.

### TRD-C6 — Prompt-content CLI source privacy

Issue #116 is PLANNED. The `count-tokens` command must not require **prompt content** in **process argv**. A reviewed replacement shall expose exactly one selected bounded non-argv source, such as stdin, an inherited file descriptor, or a deliberately opened file surface; impose finite input bytes/characters before tokenization; define deterministic UTF-8 and terminal-newline behavior; and reject conflicting sources before database/tokenizer work. Rejected input diagnostics must never echo prompt content. The production text itself must remain intact for purpose-bound token counting rather than being destructively masked, and PostgreSQL `pg_tiktoken` remains the token authority. Implementation waits for #85/#87 to settle their overlapping CLI/resource ownership.

### TRD-C7 — Credential-bearing PostgreSQL DSN CLI source authority

Issue #117 is PLANNED. A **credential-bearing PostgreSQL DSN** must not cross **process argv** in the standalone CLI. If argv retains any DSN-like locator, it must be explicitly classified credential-free; password-bearing connection authority must come from the established environment/secret-injection bootstrap seam or another reviewed bounded non-argv source. Preserve #89's exact explicit-versus-ambient source precedence and #87's store/connection ownership and validation. Unsafe, blank, ambiguous, or wrongly typed DSN inputs must fail **before libpq** target selection where the package owns the boundary, and rejected diagnostics must not reflect credential-bearing DSN content. Implementation waits for #85/#87/#89 to integrate or be superseded.

### TRD-C8 — Explicit provider-secret encryption policy (Issue #121) — PLANNED

Provider-secret persistence must gain an explicit **encryption-required** deployment mode while retaining a deliberate local/development compatibility mode. Protected main's Base64 path remains obfuscation, **not encryption**. In encryption-required mode, missing or unusable **Fernet** authority must fail before a provider-secret write; existing `is_encrypted = FALSE` rows must be detected before activation and either re-encrypted atomically or leave activation failed without destructive loss. The implementation must define bounded **key rotation**/recovery, prevent secret/ciphertext/key/credential-bearing-DSN disclosure in diagnostics or readiness, and preserve host-provided credential providers. Detailed migration, MultiFernet-or-equivalent rotation constraints, rollback, and acceptance are owned by `docs/adr/provider-secret-encryption-policy.md`. Implementation waits for #85/#87/#89 to integrate or be superseded.

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

### TRD-O4 — Operation span failure status overlay

**ACTIVE-PR #106** makes propagated operation failures queryable by setting OpenTelemetry `StatusCode.ERROR` **without a description** while retaining the package's stricter confidentiality boundary: automatic exception recording remains disabled, provider/caller exception messages are not copied into span status, and the existing finite `error.type` vocabulary remains the only package-owned error attribute. The **success status unset** behavior is deliberate and must remain the OpenTelemetry default rather than synthesizing an OK status.

Status construction and mutation are best-effort telemetry. An unavailable optional trace-status API, an ordinary telemetry failure during status construction, or `span.set_status()` failure must not replace the exact provider/application result or exception. This overlay remains ACTIVE-PR until #106 or a reviewed successor reaches protected main and receives fresh validation.

### TRD-O5 — PostgreSQL logging privacy overlay

**ACTIVE-PR #119** governs the optional PostgreSQL monitoring example. It must disable package-default persistent SQL statement/bind-value logging and `pg_stat_statements` query-text collection/persistence while preserving purpose-bound application data. The contract must explicitly distinguish those persistent secondary copies from `pg_stat_activity`: with `track_activities = on`, PostgreSQL can expose bounded current/recent **query text** in volatile activity state, with this example bounding the text by `track_activity_query_size = 1024`.

That residual live-query surface is privileged operational data, not a claim of content-free telemetry. Deployments must restrict superuser/`pg_read_all_stats` access and audit privileged use; deployments that opt out with `track_activities = off` accept the corresponding operability loss. Content-bearing server logs or `pg_stat_statements` may be enabled only under an explicit purpose, authorization, retention/deletion, encryption/storage, access-audit, and incident contract. These controls are selective disclosure and do not by themselves prove CSAP, SOC 2, or other certification.

### TRD-O6 — Container-native storage-bounded PostgreSQL logging (Issue #120) — PLANNED

After #119 establishes the privacy-safe event/content baseline, the standalone/container logging path must become **container-native** and **storage-bounded** without regressing that boundary. A supported deployment shall be able to route PostgreSQL operational records through stdout/stderr and the container runtime/platform logging path without requiring unmanaged package-owned file accumulation. If a PostgreSQL-managed file destination remains supported, its storage budget, cleanup prerequisite, rotation behavior, and rollback must be explicit; rotation alone is not business **retention**. Kubernetes/Compose guidance may delegate retention, encryption, access control, export, and deletion to host logging infrastructure, but must preserve #119's SQL/bind/query-stat and client-network disclosure constraints and verify that logs remain retrievable after startup without changing readiness/database behavior.

## 8. Readiness and deployment requirements

### TRD-R1 — Readiness decision

Protected main treats database, `pg_tiktoken`, and `com_config` as required readiness components and exposes a CLI health command plus `/healthz`. Current behavior includes component details and a simple HTTP server. `ACTIVE-PR` #70 owns stronger redaction, bounded concurrency, database statement timeout, request-read timeout, and listener defaults, plus exact listener-input validation before socket creation: host must be an exact non-empty string with no leading/trailing or embedded whitespace and no ASCII C0 control or DEL characters; the accepted host is not trimmed or stringified; port must be a non-boolean integer in `1..65535`. The same ACTIVE-PR keeps the bundled container command boundary out of a shell: both the readiness-server command and Docker healthcheck are **exec-form** JSON at the fixed image default port `8080`, and environment-controlled health-port text is not shell-expanded before Python validation. A deployment that needs another health port must explicitly override both executable command and healthcheck rather than relying on a shell-interpolated environment knob.

### TRD-R2 — Standalone Compose

The bundled Compose file provides PostgreSQL and component services and uses bootstrap DSN transport. Protected main publishes 5432/8080 without an explicit host IP. `ACTIVE-PR` #91 is the loopback-only standalone target and defines the complete host-published service allow-list: exactly the PostgreSQL service on TCP 5432 and the component service on TCP 8080, each published once to loopback. A third host-published service or an extra published port is outside that allow-list and must fail the deployment contract rather than being silently accepted.

### TRD-R3 — Embedded deployment

Embedding services may import the package directly and own ingress, service identity, DSN acquisition, tenant authorization, external secret management, telemetry resource/export configuration, and higher-level transaction boundaries.

### TRD-R4 — Deployment-specific standalone database credential

Issue #99 is PLANNED after #91 settles the authoritative Compose network surface. A fresh standalone deployment must not rely on the repository-wide literal PostgreSQL password as an authentication default. PostgreSQL and the component must share one deployment-specific operator-provided or generated bootstrap credential without placing that credential in committed files, process argv, shell-interpreted text, logs, or evidence; arbitrary supported secret characters, wrong-secret rejection, restart persistence, and recovery must be tested.

## 9. Reliability and recovery requirements

### TRD-REL1 — Idempotent local preparation

Batch preparation and persistent identities shall support safe retry/restart behavior rather than silently appending or duplicating prepared artifacts for an already-established batch identity.

### TRD-REL2 — Lifecycle reconciliation

Durable lifecycle errors shall retain enough bounded phase/operation/order/validated-identity information for reconciliation without placing provider-controlled bodies into exported diagnostics.

### TRD-REL3 — Checkpoint target

`ACTIVE-PR` #59/#60 defines resumable prefix evidence and durable compare-and-swap checkpoint storage. The package shall not call that distributed exactly-once delivery; external side effects across systems require host idempotency/outbox/reconciliation.

### TRD-REL4 — Audit target

`ACTIVE-PR` #94/#96/#97 defines the current linearized append-only acceptance evidence, stable pagination, and snapshot-manifest chain. #79/#83/#84 are superseded implementation lines and their checks/reviews do not transfer. Audit evidence does not make a PostgreSQL owner/superuser cryptographically unable to modify data; that residual boundary must remain explicit.

### TRD-REL5 — Automatic provider reconciliation after SQL retirement

Issue #102 is the PLANNED **automatic provider reconciliation** replacement for the unsafe retired SQL polling behavior. It must operate on validated durable endpoint + provider remote identities, call the existing Python provider/credential boundary, impose a finite per-run work budget, and define single-flight or equivalent concurrency plus crash/restart reconciliation semantics. External scheduling authority must remain separate from provider credentials. The worker must not imply **distributed exactly-once** delivery; cross-system side effects still require explicit host idempotency/outbox/reconciliation where the package contract does not own them.

### TRD-REL6 — Package-owned PostgreSQL wait budgets (Issue #122) — PLANNED

Package-created database work must gain finite, explicit **PostgreSQL connection timeout** and operation-class-specific statement/lock wait budgets. Protected main currently creates core connections with ordinary `psycopg.connect(dsn)` and has no general package-owned statement timeout outside the separately hardened readiness target. The planned implementation shall compose a finite libpq `connect_timeout` without rewriting the caller-selected DSN authority; use transaction/session-local `statement_timeout` and a bounded lock-wait policy where the package owns the transaction; distinguish ordinary reads/writes from longer migration operations; and avoid silently changing caller-owned/injected transaction settings.

A timeout must abort or roll back the affected package-owned transaction before completion is reported. Exported diagnostics shall identify only a bounded operation/phase category and must not copy DSNs, SQL text, bind values, credentials, prompts, provider payloads, or arbitrary database exception text. Realistic PostgreSQL integration tests must cover lock contention, statement cancellation/rollback, recovery/retry, and normal fast paths. This remains PLANNED until #87/#89 and the #53 durable transaction stack integrate or are superseded; #70's readiness-specific database timeout remains an independent contract.

## 10. CI, evidence, and review requirements

### TRD-E1 — Deterministic quality gate

Repository CI shall cover supported Python versions, non-integration tests, compile, Ruff, 100% owned production statement/branch coverage, 100% public docstrings, lock freshness, package build, Compose validation, and component/PostgreSQL image build as applicable to the live workflow.

### TRD-E2 — Exact source identity target

Protected-main CI currently uses default checkout behavior for `pull_request`; GitHub documents that this checks out the generated merge ref. `ACTIVE-PR` #88 binds checkout/verification to `github.event.pull_request.head.sha`. Until integrated, generated-merge CI is useful compatibility evidence but must not be mislabeled exact source-head proof.

### TRD-E3 — Evidence-class separation

The following are distinct and non-substitutable: contributor/source head, PR base snapshot, live base ref tip, synthetic merge commit, commit status/check run, workflow checked-out commit, formal review, unresolved thread state, independent approval, branch protection/ruleset, security finding, release artifact/provenance evidence.

### TRD-E4 — Independent review

Where repository/CWL policy requires qualifying independent non-author approval, no author comment, bot status, synthetic text, reaction, old-head review, or COMMENTED review is equivalent to that approval.

### TRD-E5 — Declared Python compatibility matrix

Issue #113 is PLANNED. Release evidence must make `Requires-Python` and tested supported minors consistent: either exercise every claimed minor through the supported matrix or narrow the declared range. Python 3.14 remains required. This composes with #88 exact-source CI and #57 release/package evidence and must not weaken either gate.

### TRD-E6 — Deterministic uv toolchain

**ACTIVE-PR #114** owns the repository **uv toolchain** pin through root `uv.toml` `required-version`, independently of the immutable setup action. The pinned executable version must drive locked sync/build checks uniformly; updates require reviewed reproducibility and rollback evidence. This remains ACTIVE-PR until protected integration and exact-source revalidation.

### TRD-E7 — Locked CI quality tools

Issue #115 is PLANNED. CI-only Python **quality tools** that determine coverage, docstring, and release evidence must resolve from a reviewed lock or equivalently immutable governed descriptor rather than ad hoc `uvx`/`--with` resolution. Their exact versions and source identity must be auditable and included in supply-chain evidence without coupling model or reviewer credentials.

## 11. Packaging and release requirements

### TRD-PKG1 — Package metadata

Protected main builds `pg-llm-batch` version `0.1.0`, Python >=3.10, Apache-2.0, with `LICENSE` and `NOTICE` included and a console script `pg-llm-batch`.

### TRD-PKG2 — Reproducibility target

`ACTIVE-PR` #57 owns descriptor-pinned clean-archive reproducibility evidence. Publication/attestation authority remains separate from read-only verification.

### TRD-PKG3 — Protected integration only

Version bump, release creation, publication, and provenance acceptance shall use an exact integrated protected head after all required checks, independent review, security, packaging, migration/recovery, and operational gates are satisfied.

### TRD-PKG4 — Reproducible component-image OS dependency set

Issue #100 is PLANNED after #70 settles the authoritative Dockerfile command/healthcheck surface. Ordinary builds must not perform an unconstrained distribution upgrade or resolve unversioned operating-system packages from mutable repository state. The selected snapshot/version mechanism, package-source identity, resolved package set, controlled refresh procedure, rollback/emergency update path, and SBOM/provenance binding must be machine-checkable on the final source.

### TRD-PKG5 — Single authoritative version source

Issue #109 is a PLANNED release-integrity follow-up. Package metadata, the importable `__version__`, generated artifacts, release tags, and release acceptance evidence must derive from a **single authoritative version** source or from a machine-checked deterministic projection of that source. Drift between `pyproject.toml`, package runtime metadata, built distributions, and release/tag evidence must fail before publication, with rollback/recovery documented for an interrupted version bump.

### TRD-PKG6 — Typed package marker

Issue #112 is PLANNED. The build backend and package configuration must include an exact `py.typed` marker in wheel and sdist outputs and in the installed distribution, with clean-archive reproducibility checks. This is package metadata/data rather than a runtime dependency and waits for #57/#53 package ownership to settle before implementation.

### TRD-PKG7 — Reproducible PostgreSQL image inputs (Issue #118) — PLANNED

The **PostgreSQL image** build must make Debian package source/version identity, build-only toolchain inputs, the exact `pg_tiktoken` commit and patch, and the resulting Rust dependency graph deterministic and reviewable. Ordinary release builds must not perform an unconstrained distribution upgrade or run an unreviewed live-registry dependency resolution in place of a repository-owned immutable descriptor. A reviewed lock or equivalent evidence must support fail-closed locked fetch/install, and SBOM/provenance must bind the declared PostgreSQL image inputs to the resulting image. This remains distinct from component-image Issue #100 and must wait for the active #94→#97 Dockerfile owner plus #101/#103 migration/package boundaries rather than race them.

## 12. Documentation requirements

The repository shall keep a canonical PRD, TRD, Architecture, UML, ERD, Threat Model, Data Governance, Test Strategy, Operability guide, ADR index, automation-governance ADRs, and Traceability matrix. Each must distinguish `IMPLEMENTED-ON-PROTECTED-MAIN` from `ACTIVE-PR` and must be tested for presence/core authority terms.

## 13. Authoritative references

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://www.rfc-editor.org/rfc/rfc9110.html

GitHub. (2026). *Events that trigger workflows*. GitHub Docs. https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Database connection control functions*. https://www.postgresql.org/docs/18/libpq-connect.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Client connection defaults*. https://www.postgresql.org/docs/18/runtime-config-client.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Row security policies*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html