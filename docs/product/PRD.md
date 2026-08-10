# pg-llm-batch Product Requirements Document

- **Document status:** Proposed canonical authority on PR #93
- **Product:** `pg-llm-batch`
- **Current release on protected-main baseline:** `0.1.0`
- **Protected-main reference used for this edition:** `bf2cc2e140dc3ff4a56c3203f80f41bb9fed5d10`
- **Maturity discipline:** protected-main behavior is `IMPLEMENTED-ON-PROTECTED-MAIN`; open-PR behavior is `ACTIVE-PR` and is never represented as shipped.

## 1. Product mission

`pg-llm-batch` is a PostgreSQL-centered LLM batch engine that can run as a standalone component or be embedded in another service. Its job is to turn database-backed LLM requests into bounded JSONL batch payloads, submit them to an OpenAI-compatible Files/Batches API, observe remote lifecycle state, and retrieve results without forcing every embedding product to reimplement token accounting, batch construction, provider transport hardening, persistence, and operational controls.

The product optimizes for **deterministic correctness, bounded resources, restart/reconciliation evidence, composability, and defensible operational/security boundaries** rather than maximum request throughput at any cost.

## 2. Primary users and buyers

### 2.1 Application integrator

Needs a Python package that can be embedded into an existing service while preserving host ownership of authentication, tenancy, OpenTelemetry SDK/exporters, deployment topology, and higher-level business transactions.

### 2.2 Platform / AI operator

Needs a standalone PostgreSQL-backed batch component with CLI, Docker deployment, health checks, database configuration/secrets, provider lifecycle state, and bounded failure behavior.

### 2.3 SRE / security / compliance reviewer

Needs explicit trust boundaries, bounded network and memory behavior, auditable durable state, predictable recovery/rollback, least-privilege integration seams, and evidence that CI/review/release claims correspond to the exact source under review.

### 2.4 Acquisition / technical diligence reviewer

Needs the repository to explain what is shipped, what is still an active PR, why key architecture decisions were made, how data moves and persists, how release evidence is produced, and which risks remain host-owned.

## 3. Jobs to be done

1. **Prepare batches deterministically.** Given queued PostgreSQL requests and provider limits, count tokens through `pg_tiktoken`, construct bounded payloads, and persist enough database state to reconstruct them without temporary files.
2. **Submit and operate remote batch jobs safely.** Upload payloads, create jobs, poll, wait, cancel, and retrieve through an OpenAI-compatible API with explicit credential and destination validation.
3. **Bound untrusted provider behavior.** Apply finite time, retry, decoded-byte, identifier, JSON, and URL contracts so provider or intermediary behavior cannot create unbounded application work or ambiguous follow-up requests.
4. **Preserve restart/reconciliation evidence.** Record remote lifecycle observations durably; evolve toward tenant-isolated checkpoints/audit evidence only through explicit reviewed contracts.
5. **Operate standalone or embedded.** Keep core batch behavior usable without requiring a global OpenTelemetry SDK, a specific gateway vendor, or a larger ContextualWisdomLab service.
6. **Support commercial diligence.** Provide testable documentation, migration/recovery boundaries, security controls, release/provenance evidence, and clear separation of shipped versus planned functionality.

## 4. Product principles

### PRD-P1 — PostgreSQL-centered authority

For package-owned batch configuration, queue/batch/request/payload state, endpoint/tokenizer mapping, and durable remote lifecycle state, PostgreSQL is the durable authority on protected main. Provider APIs are external systems whose responses are untrusted inputs that must be validated before they become durable package state.

### PRD-P2 — Standalone plus modular MSA interoperability

The same package must remain usable in a standalone Docker/CLI deployment and inside a larger service. Host applications may inject credential providers and, where supported, observability/persistence seams instead of being forced to adopt a package-owned global runtime.

### PRD-P3 — Bounded-by-default behavior

Network requests, provider-control JSON, provider-file downloads, retries, identifiers, request paths, and batch resource limits must be finite and validated. A provider failure must not silently widen replay, memory, or credential exposure.

### PRD-P4 — Explicit authority and no false guarantees

The package must not claim distributed exactly-once delivery, provider authentication beyond the configured TLS/credential boundary, full-stream immutability from a prefix checkpoint, tenant authorization where the host remains responsible, or certification it has not earned.

### PRD-P5 — Evidence over narrative

Commercial acceptance depends on exact tests, security gates, durable schema/API contracts, and independent review—not PR prose or an older green commit.

### PRD-P6 — Purpose-bound data governance

Prompts, provider results, credentials, lifecycle metadata, and telemetry shall follow the canonical engineering boundary in `docs/DATA_GOVERNANCE.md`. The product shall preserve purpose-bound prompt/result utility where the workflow requires it rather than treating blanket masking as authorization. Business purpose, subject/workload authorization, retention, erasure/export, backup, and residency remain **host-owned** unless a future accepted package contract explicitly moves part of that authority into pg-llm-batch.

## 5. Protected-main product requirements

The following requirements describe the as-built protected-main baseline used for this edition.

### PRD-R1 — Database-authoritative token counting

The engine shall support token counting through PostgreSQL `pg_tiktoken` and use that result when constructing provider batch payloads.

**Protected-main evidence:** `pg_llm_batch/token_counter.py`, `pg_llm_batch/orchestrator.py`, bundled PostgreSQL image.

### PRD-R2 — Disk-free payload assembly

Prepared JSONL payloads shall be persisted/reconstructable through PostgreSQL state rather than requiring package-owned temporary payload files.

**Protected-main evidence:** `llm_batch_file_payloads`, `llm_batch_files`, `llm_jsonl_lines`, `load_virtual_payload()`.

### PRD-R3 — OpenAI-compatible provider workflow

The package API shall support upload, batch creation, status polling, bounded waiting, cancellation, and result retrieval through the Files/Batches API shape used by OpenAI-compatible endpoints. The protected-main CLI exposes `submit`, `poll`, `wait`, and `retrieve`; an operator-facing `cancel` command is PLANNED in Issue #90 and is not shipped on this baseline.

**Protected-main evidence:** `BatchAPIClient` for provider operations and the parser surface in `pg_llm_batch/cli.py` for current operator commands.

### PRD-R4 — Credential-source separation

Provider URLs and API keys shall be resolved through a pluggable credential provider. The built-in path stores configuration and secrets in PostgreSQL; environment variables are bootstrap transport only where explicitly documented.

### PRD-R5 — Safe provider destination and identifier handling

Credential-bearing remote calls shall reject ambiguous or unsafe gateway destinations and unsafe provider resource identifiers before constructing authenticated follow-up requests. Non-loopback production destinations require HTTPS.

### PRD-R6 — Bounded provider responses

Files/Batches control-plane JSON shall be decoded under an independent bounded budget. Provider result/error files shall be streamed under a finite decoded-byte ceiling and strict UTF-8/JSONL handling.

### PRD-R7 — Bounded idempotent retries

Protected main shall automatically retry only the reviewed idempotent GET failure/status classes within finite attempt and delay bounds and shall honor bounded standards-compliant `Retry-After` guidance. Side-effecting POST operations shall remain single-attempt unless a separately reviewed idempotency contract explicitly changes that rule.

### PRD-R8 — Durable remote lifecycle projection

The package shall offer a client that reserves database-owned observation order before provider I/O and persists validated create/poll/accepted-cancel lifecycle observations to `llm_remote_batch_jobs`.

### PRD-R9 — Optional operation observability

Hosts that already operate OpenTelemetry shall be able to opt into bounded operation spans/metrics without the base package configuring a global SDK/exporter. Package-owned telemetry shall use low-cardinality, privacy-bounded attributes.

### PRD-R10 — Standalone operator surface

The package shall provide a CLI, Docker images/Compose example, schema initialization, configuration/secret commands, provider operation commands, and readiness interfaces sufficient for a standalone deployment. The command-level compatibility surface is enumerated in `docs/product/API_CONTRACT.md`; planned commands are not implied by this general requirement.

### PRD-R11 — Hard quality thresholds

Owned production code shall maintain 100% statement and branch coverage and 100% public docstrings under repository policy; supported CI Python versions are 3.10, 3.12, and 3.14 on the protected-main baseline.

## 6. Active product targets

These are **ACTIVE-PR** or explicitly **PLANNED**, not shipped requirements. They are listed because they materially define the accepted product direction and must be visible to diligence readers.

### PRD-T1 — Tenant-isolated lifecycle state (#53)

Introduce trusted host-selected tenant scope and fail-closed PostgreSQL row-level isolation for durable lifecycle state while preserving standalone compatibility.

### PRD-T2 — Reproducible release evidence (#57)

Produce read-only, descriptor-pinned, reproducible wheel/sdist evidence before publication authority is considered.

### PRD-T3 — Incremental result streaming (#58)

Provide bounded record iteration so large provider result/error files need not be fully materialized as aggregate lists.

### PRD-T4 — Resumable checkpoints (#59, #60)

Create immutable prefix checkpoints and package-owned durable PostgreSQL checkpoint persistence with explicit compare-and-swap and transaction boundaries; do not claim full-stream attestation or distributed exactly-once delivery.

### PRD-T5 — Checkpoint observability and auditability (#92, #94, #96, #97)

Add optional checkpoint telemetry, append-only acceptance evidence, bounded stable export, and deterministic snapshot manifests while preserving tenant and evidence boundaries. These PRs are the current linearized replacements; #78, #79, #83, and #84 are superseded implementation lines and their evidence does not transfer.

### PRD-T6 — Atomic migration operation (#95)

Make related checkpoint/audit migrations an all-or-nothing operator action with bounded source and rollback/concurrency verification. #95 is the current replacement; #80 is superseded.

### PRD-T7 — Health/deployment hardening (#70, #91)

Redact public readiness diagnostics, bound health work/concurrency/read duration, default direct CLI listening to loopback, and bind standalone Compose publications to loopback unless a deployment explicitly opts into broader ingress.

### PRD-T8 — Provider retry trust hardening (#71)

Extend the reviewed GET retry set with HTTP 425 while treating TLS/certificate/fingerprint identity failures as permanent single-attempt failures and keeping transport diagnostics in a bounded vocabulary.

### PRD-T9 — Secret/config/bootstrap lifecycle hardening (#85, #86, #87, #89)

Remove plaintext secret values from argv, canonicalize typed configuration ownership, deterministically close package-owned database sessions, and make explicit bootstrap-source precedence fail closed on blank targets.

### PRD-T10 — Exact source evidence and maintenance governance (#88, #69, #93)

Bind CI evidence to the exact source head, harden scheduled maintenance authority, and make the product/technical/documentation/evidence graph reconstructable from the repository itself.

### PRD-T11 — Operator cancellation CLI (Issue #90) — PLANNED

Expose the existing validated provider cancellation primitive through a first-class `cancel --endpoint <alias> --batch-id <id>` operator command without adding automatic retry to the side-effecting cancellation request. This slice remains PLANNED while overlapping CLI secret-input/resource-ownership work in #85 and #87 is active and requires final exact-source acceptance after #88; it must not be represented as a protected-main CLI capability before those dependencies are resolved and the implementation is integrated.

### PRD-T12 — Strict provider progress/control JSON (Issue #98) — PLANNED

Reject malformed provider `request_counts` shapes, booleans/negative/string counters, and non-finite control JSON such as `NaN` or `Infinity` through one bounded package error rather than raw Python exceptions or non-standard structured output. Preserve the response-size, UTF-8, retry/replay, and provider-error confidentiality contracts owned by #71; implementation waits until that overlapping provider-control surface integrates or is superseded.

### PRD-T13 — Deployment-specific PostgreSQL authentication (Issue #99) — PLANNED

Remove the shared default PostgreSQL credential from standalone Compose without weakening #91's loopback publishing boundary. Fresh deployments must use an operator-provided or generated deployment-specific credential that is not committed, placed in process argv, shell-interpreted, or copied into logs/evidence; restart recovery and supported secret-character handling must be deterministic.

### PRD-T14 — Reproducible component container-image OS dependencies (Issue #100) — PLANNED

Make the component container image's operating-system package set reproducible and reviewable rather than depending on mutable `apt-get upgrade`/unversioned repository state. Preserve the non-root/no-shell readiness contracts owned by #70 and bind the resolved package set into SBOM/provenance evidence.

### PRD-T15 — Retire direct-SQL provider retrieval (#101) — ACTIVE-PR

Decommission the legacy `pg_cron` + `pgsql-http` direct-SQL provider retriever fail-closed. That path reads weaker database-visible secret material and treats a local batch UUID as a provider remote batch identifier without a reviewed identity binding. #101 keeps historical retrieval logs, unschedules only the exact legacy job, removes its helper functions, and leaves provider HTTP authority with `BatchAPIClient` / `DurableBatchAPIClient` rather than creating a second credential/network implementation in PostgreSQL.

### PRD-T16 — Automatic provider reconciliation (Issue #102) — PLANNED

Restore buyer-visible automatic provider reconciliation after #101 without resurrecting direct-SQL provider HTTP. A replacement worker/scheduler seam must operate only on validated durable remote identities, use the existing Python credential/destination/retry/response boundaries, be concurrency/restart safe under a finite work budget, and keep scheduling authority separate from provider credentials. It must not claim distributed exactly-once delivery and must wait for overlapping durable-lifecycle/resource-ownership surfaces when necessary.

### PRD-T17 — OpenTelemetry optional dependency and live conformance (Issue #107) — PLANNED

Make the documented optional operation-observability surface installable through a first-class package extra instead of requiring operators to reproduce a doctoring-only dependency constraint manually. The base package dependency set must remain unchanged; the planned extra must declare the supported `opentelemetry-api` range, keep SDK/exporter configuration host-owned, and add live optional-API conformance that proves success retains the default Unset span status while propagated failure receives the description-free Error semantics defined by ACTIVE-PR #106. This remains PLANNED while #57 owns release/package metadata and #106 owns the current operation-span status contract.

### PRD-T18 — Endpoint-qualified tokenizer authority (Issue #108) — PLANNED

Make tokenizer/model metadata endpoint-qualified and ambiguity-safe instead of selecting among duplicate provider-facing `model_id` rows by recency alone. A trusted endpoint identity must govern endpoint-specific tokenizer metadata, cross-endpoint ambiguity must fail closed, and stale `pg_cron` model-sync documentation must be removed unless a supported scheduler actually exists. Implementation waits for #87's active `TokenCounter` ownership and composes with #53 if tenant-qualified endpoint authority is required.

### PRD-T19 — Single authoritative package version (Issue #109) — PLANNED

Establish one machine-readable **single authoritative version** source so source checkout, built wheel/sdist metadata, installed distribution metadata, `pg_llm_batch.__version__`, SBOM/provenance, and release evidence cannot silently diverge. This is not a version bump. Implementation waits for #57's package/release metadata and the #53 stack's package-root surface to integrate or be superseded.

### PRD-T20 — Explicit HTTP session ownership (Issue #110) — PLANNED

Make `BatchAPIClient` **HTTP session ownership** deterministic for callers that use the async API outside `async with`. Provide an idempotent async cleanup contract such as `aclose`, define reopen/closed-client semantics and context nesting, and never close caller-owned shared sessions. Implementation waits for #71 because that PR is currently authoritative for `batch_api_client.py`; later composition must preserve #87 resource-lifecycle semantics where applicable.

### PRD-T21 — Credential resolution concurrency (Issue #111) — PLANNED

Move package-provided synchronous PostgreSQL **credential resolution concurrency** off the asyncio event-loop thread, or introduce an explicit bounded async resolver contract with a compatibility adapter. Resolution needs its own finite time/resource and cancellation policy, bounded worker/connection fan-out, deterministic connection ownership, and confidentiality-preserving errors. Implementation waits for #71 and adjacent #87/#86/#89 configuration/resource surfaces to settle and must not solve blocking by indefinitely caching plaintext secrets.

### PRD-T22 — Typed-package marker (Issue #112) — PLANNED

Publish a standards-conformant `py.typed` marker with the built distribution so downstream type checkers can treat the package's inline annotations as supported package data. The marker, wheel/sdist contents, installed distribution, and package-data configuration must remain reproducible and machine-checked. Implementation waits for #57/#53 package-surface ownership to settle and must not modify their active metadata in parallel.

### PRD-T23 — Declared Python compatibility evidence (Issue #113) — PLANNED

Reconcile `Requires-Python >=3.10` with evidence across every claimed supported minor, or narrow the declared compatibility range to exactly what the release process proves. The target must make the declared `Requires-Python` contract, CI matrix, built metadata, and release acceptance agree rather than silently skipping unsupported minors; implementation composes with #88 exact-source CI and #57 release/package evidence.

### PRD-T24 — Deterministic uv toolchain (#114) — ACTIVE-PR

Pin the repository `uv toolchain` version independently of the immutable setup action so dependency/environment/package operations do not drift as `latest` changes. ACTIVE-PR #114 owns the root `uv.toml` exact requirement and its reproducibility/rollback contract; it does not change runtime package dependencies or package version.

### PRD-T25 — Locked CI quality tools (Issue #115) — PLANNED

Move CI-only Python `quality tools` such as coverage/docstring tooling into reviewed dependency evidence instead of resolving ad hoc tool versions outside the project lock. The final design must keep the quality gate independently auditable, bind resolved tools into SBOM/provenance or equivalent governed evidence, preserve Python 3.14, and wait for #114/#88/#57 ownership boundaries before changing shared package/CI surfaces.

### PRD-T26 — Prompt-content input outside process argv (Issue #116) — PLANNED

Move `count-tokens` **prompt content** out of **process argv**. Add one bounded non-argv input authority such as stdin, a file descriptor, or a reviewed file-input surface; require exactly one selected text source, a finite byte/character budget, deterministic UTF-8 and newline semantics, and no rejected prompt reflection into diagnostics. Preserve the actual purpose-bound prompt content for token counting rather than blanket masking, and keep PostgreSQL `pg_tiktoken` as the token authority. Implementation waits for #85/#87 CLI and resource ownership to integrate or be superseded.

### PRD-T27 — Credential-bearing PostgreSQL DSNs outside process argv (Issue #117) — PLANNED

Prevent **credential-bearing PostgreSQL DSNs** from crossing the standalone CLI **process argv** boundary. Allow only explicitly classified credential-free locator forms in argv if retained at all; password-bearing connection authority must come from a secure bootstrap source such as the environment/secret-injection seam or another bounded non-argv mechanism. Preserve #89 explicit source precedence and #87 connection ownership/validation, reject unsafe or ambiguous DSN values before libpq, and never reflect rejected DSN content. Implementation waits for #85/#87/#89 to settle.

### PRD-T28 — PostgreSQL logging privacy (#119) — ACTIVE-PR

Harden the optional PostgreSQL monitoring example using **selective disclosure** rather than blanket masking. ACTIVE-PR #119 disables package-default persistent SQL statement/bind-value logging and `pg_stat_statements` query-text collection/persistence while preserving the authorized production data needed by the batch workload. It explicitly retains bounded, **volatile** live `pg_stat_activity` query text while `track_activities` is enabled, treats privileged statistics access as deployment-owned authorization, and requires content-bearing audit/query-stat channels to have explicit purpose, least-privilege access, retention/deletion, encryption/storage, and incident handling. This does not claim that all PostgreSQL query text is absent, that the optional file is loaded automatically, or that any logging setting proves CSAP/SOC 2 or other certification.

### PRD-T29 — Reproducible PostgreSQL image inputs (Issue #118) — PLANNED

Make the **PostgreSQL image** dependency graph explicit and reviewable instead of allowing ordinary release builds to resolve mutable Debian package state or regenerate the patched `pg_tiktoken` Cargo dependency graph from a live registry. The target keeps the exact `pg_tiktoken` source commit and fail-closed patch identity, removes unconstrained distribution upgrade drift, binds Debian source/package versions and a reviewed Cargo lock or equivalent immutable descriptor into SBOM/provenance, and proves clean rebuild dependency identity. This remains distinct from component-image Issue #100 and must not race the active #94→#97 PostgreSQL Dockerfile stack or bypass the #101/#103 existing-volume migration boundary.

### PRD-T30 — Container-native storage-bounded PostgreSQL logging (Issue #120) — PLANNED

After ACTIVE-PR #119 settles the privacy-safe PostgreSQL logging content boundary, make standalone/container log routing **container-native** and **storage-bounded** without reintroducing SQL, bind-value, connection-event, or query-stat disclosure. A supported container deployment shall be able to use stdout/stderr plus the container runtime or platform logging path, while any retained PostgreSQL-managed file profile must state its storage and cleanup prerequisites explicitly. File rotation is not business **retention**: retention, deletion, export, legal hold, residency, and external log shipping remain deployment-owned governance. This follow-up must preserve #119's selective-disclosure baseline and prove log retrieval after startup without weakening readiness or database behavior.

## 7. Non-goals and explicit exclusions

- **OUT-OF-SCOPE:** training or serving language models.
- **OUT-OF-SCOPE:** replacing a general-purpose job scheduler, workflow engine, or message bus.
- **OUT-OF-SCOPE:** acting as a universal secret-management system; the built-in secret store is a package integration boundary, and host-managed credential providers remain supported.
- **OUT-OF-SCOPE:** claiming distributed exactly-once semantics across PostgreSQL and external provider/business systems without a host-owned outbox/idempotency/reconciliation design.
- **OUT-OF-SCOPE:** inferring tenant identity from provider metadata, endpoint aliases, request bodies, remote IDs, or transport headers.
- **OUT-OF-SCOPE:** making a documentation/check status equivalent to independent approval or release authorization.

## 8. Commercial acceptance criteria

A commercially defensible integrated release requires all of the following on the exact protected source head:

1. product requirements that are claimed shipped are implemented and traceable to source/schema/tests;
2. supported Python/version/package/container gates pass under repository policy;
3. owned production statement/branch and public-docstring thresholds are satisfied;
4. security/SAST/dependency/supply-chain/provenance gates required by live policy pass;
5. migrations and rollback/recovery contracts are deterministic and tested where applicable;
6. health, startup, provider, and operator workflows have bounded failure behavior;
7. canonical PRD/TRD/Architecture/UML/ERD/Threat Model/Data Governance/Test Strategy/Operability/Traceability remain code-current;
8. zero valid unresolved review/security findings remain;
9. a qualifying independent non-author formal approval exists when policy requires it; and
10. release/publication occurs only after protected integration and release acceptance, never from a predecessor or synthetic-only evidence state.

## 9. Success measures

Success is evaluated primarily through correctness and operations evidence rather than vanity traffic metrics:

- reproducible batch construction for the same database inputs/configuration;
- no unbounded provider body or retry path owned by the package;
- restart/reconciliation state sufficient for supported lifecycle workflows;
- deterministic failure classes and actionable operator diagnostics without exposing sensitive provider payloads;
- clear shipped-vs-active-vs-out-of-scope documentation;
- repeatable migration/rollback and release evidence where those capabilities exist; and
- decreasing diligence dependence on maintainer oral history.

## 10. Product decision ownership

Product behavior is governed by protected source/schema plus accepted ADRs. Active PRs may refine the target but do not supersede protected-main truth until integrated. Scientific or security decisions that cannot be reconciled through tests, standards, or least-privilege design require explicit maintainer resolution rather than silent assumption.