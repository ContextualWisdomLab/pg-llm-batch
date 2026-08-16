# Product Requirements Document

## Document authority

This PRD defines the product contract for `pg-llm-batch`. Repository behavior is authoritative only after it is integrated into the protected default branch. Pull requests, issue plans, historical branches, generated merge commits, workflow artifacts, and review commentary are evidence or work-in-progress, not shipped product truth.

Use these status terms consistently:

- **IMPLEMENTED-ON-PROTECTED-MAIN** — present in the protected default-branch tree and covered by its repository contract.
- **ACTIVE-PR** — implemented or being repaired in an open pull request; not shipped.
- **PARTIAL** — a protected-main primitive exists, but an end-to-end product capability still has an explicit gap.
- **PLANNED** — accepted requirement without an integrated implementation.
- **SUPERSEDED** — historical implementation or proposal that is not current product authority.

## Product purpose

`pg-llm-batch` is a standalone and embeddable PostgreSQL-centered engine for preparing, submitting, observing, and retrieving bounded LLM Batch API workloads. It is intended for operators and host applications that need durable batch state, deterministic token/resource accounting, explicit tenant boundaries, bounded provider I/O, and acquisition-grade operational evidence without coupling the package to one gateway, scheduler, web application, or ContextualWisdomLab host service.

## Primary users

1. **Platform operators** running the package as an independently deployable service or Compose component.
2. **Application/platform engineers** embedding the Python package and PostgreSQL schema in a larger product.
3. **Multi-tenant host services** that authenticate and authorize callers before supplying a trusted `tenant_scope`.
4. **Reliability and security reviewers** who need deterministic failure boundaries, migrations, rollback, audit evidence, security gates, SBOM/provenance evidence, and bounded diagnostics.

## Product outcomes

The product must let a qualified host:

- count model tokens through the reviewed PostgreSQL tokenizer boundary;
- prepare JSONL batch payloads under finite token, byte, and record limits;
- preserve package-owned payloads and lifecycle state durably in PostgreSQL;
- submit, poll, wait, cancel, and retrieve through validated OpenAI-compatible Batch API clients;
- operate in exact `standalone` mode or with a trusted tenant-qualified lifecycle identity;
- recover or reconcile provider lifecycle state without introducing a second database-side networking authority;
- derive bounded content-free PostgreSQL recovery evidence for backup artifacts and the packaged schema without treating evidence as proof of restorability; and
- prove package quality, security, reproducibility, release-artifact identity, and rollback assumptions through repository evidence.

## Protected-main capability contract

| Capability | Status | Product requirement |
| --- | --- | --- |
| PostgreSQL token counting and bounded batch preparation | IMPLEMENTED-ON-PROTECTED-MAIN | Token/resource accounting and batch partitioning remain deterministic and finite. |
| Disk-free package payload persistence | IMPLEMENTED-ON-PROTECTED-MAIN | Package-owned JSONL payloads persist in PostgreSQL and are validated before credential/provider effects. |
| OpenAI-compatible upload/create/poll/wait/cancel/retrieve | IMPLEMENTED-ON-PROTECTED-MAIN | Provider destinations, resource identifiers, control responses, downloads, retries, and timeouts remain bounded and validated. |
| Standalone durable lifecycle | IMPLEMENTED-ON-PROTECTED-MAIN | `DurableBatchAPIClient` preserves the existing four-argument lifecycle-recorder seam `(postgres_dsn, endpoint_alias, provider_batch, observation_order)` and its default recorder stores lifecycle state under the exact `standalone` scope. |
| Tenant-qualified durable lifecycle with forced RLS | IMPLEMENTED-ON-PROTECTED-MAIN | Tenant scope comes only from a trusted host authorization boundary, is validated before any tenant-client observation reservation, credential resolution, provider I/O, or lifecycle database I/O, and qualifies lifecycle identities, conflict targets, reads, and operational status indexing; direct arbitrary SQL remains outside the isolation guarantee. |
| Durable resumable result checkpoint/CAS storage | IMPLEMENTED-ON-PROTECTED-MAIN | PostgreSQL supplies tenant-qualified durable checkpoint authority and conflict detection; this is not a distributed exactly-once claim. |
| Redacted readiness reporting | IMPLEMENTED-ON-PROTECTED-MAIN | Public readiness evidence does not disclose arbitrary lower-layer diagnostic content. |
| Scheduler-independent bounded provider reconciliation primitive | IMPLEMENTED-ON-PROTECTED-MAIN | A host can submit a finite, validated candidate set for polling/retrieval through the existing bounded provider client; candidate discovery, scheduling, and cross-process lease ownership remain outside this primitive. |
| Bounded PostgreSQL recovery receipt | IMPLEMENTED-ON-PROTECTED-MAIN | The package can encode/decode deterministic bounded content-free metadata that identifies package/source/PostgreSQL/schema/backup evidence without carrying credentials, DSNs, SQL, business payloads, or arbitrary diagnostics. |
| Bounded PostgreSQL backup-artifact integrity evidence | IMPLEMENTED-ON-PROTECTED-MAIN | The package can derive SHA-256 and byte-size evidence from one private regular backup artifact under descriptor-pinned, no-follow, finite-work constraints without executing backup or restore. |
| Bounded packaged PostgreSQL schema evidence | IMPLEMENTED-ON-PROTECTED-MAIN | The package can derive SHA-256 and byte-size evidence from the exact distributed `schema.sql` resource under a finite package-owned work budget without executing SQL or asserting live-cluster parity. |
| PostgreSQL logical backup execution | ACTIVE-PR | A `pg_dump` candidate exists in #208 but is not shipped; protected main must not be described as creating a restorable backup from the evidence primitives alone. |
| PostgreSQL logical restore execution | ACTIVE-PR | #212 is the unshipped active direct `pg_restore` successor. Predecessor #209 must not merge: its EOF-consumption check can report failure after a seekable custom-format restore has already committed. Caller-owned source trust, target isolation, libpq allowlist, transactional failure, metadata-fingerprint integrity, and permanent documentation remain unshipped. |
| Recovery evidence binding | ACTIVE-PR | A host can compose one receipt from exact inspected schema and backup-artifact evidence objects. Bind-time composition is not inspection provenance, restorability, or target isolation. |
| Live receipt re-inspection | ACTIVE-PR | A later verifier can re-hash current bytes and compare them to a stored receipt. Agreement is valid only at that inspection instant and does not remove TOCTOU or prove restore success. |
| Post-restore catalog acceptance | ACTIVE-PR | Isolated restore acceptance must fail closed on same-name catalog decoys, tenant-qualified key order, uniqueness/constraint authority, access method, and live PostgreSQL query behavior. |
| Physical/WAL/PITR recovery profile | ACTIVE-PR | A caller-owned physical recovery profile records intent and objectives only. It does not execute `pg_basebackup`, archive or replay WAL, or establish a package RPO/RTO. |
| Restore-target isolation | PARTIAL | Distinct configuration labels are not authenticated cluster isolation. End-to-end acceptance must prove the restore target is a different cluster before production safety can be claimed. |
| End-to-end PostgreSQL recovery readiness | PARTIAL | Integrated evidence primitives do not yet prove an isolated restore with schema/RLS/constraint/extension parity, migration compatibility, external key/config custody, physical/WAL/PITR recovery, or a stated RPO/RTO/HA/DR objective. |
| Durable reconciliation candidate discovery | ACTIVE-PR | Discovery must be tenant-qualified, bounded, deterministic, and database-authoritative before it can become product truth. |
| Cross-process reconciliation single-flight | ACTIVE-PR | Concurrent workers must not race the same tenant/provider identity; merge eligibility remains governed by live repository policy. |
| Existing-volume legacy `http` / `pg_cron` retirement | ACTIVE-PR | Existing deployments need fail-closed, reversible migration evidence before compatibility packages can be removed. |
| First-class OpenTelemetry installation extra | ACTIVE-PR | Ordinary installs must remain telemetry-dependency-free; the optional package graph must be locked and reproducible. |
| Autonomous package-owned reconciliation worker with crash/restart completion semantics | PARTIAL | Protected main has reconciliation and durable state primitives, but does not yet claim a complete package scheduler/worker control plane. |
| Durable result application coupled to checkpoint advancement | PARTIAL | Existing checkpoint and retrieval primitives must not be described as end-to-end exactly-once result application until a reviewed coupling contract is integrated. |

## Functional requirements

### FR-1: Batch preparation

The engine shall resolve an existing batch identity, select eligible requests, count tokens through the package tokenizer boundary, partition work under explicit provider/resource limits, and persist payload/file/line/request assignment state atomically for one preparation operation. Re-running a supported preparation path must not silently duplicate assignment or corrupt package-owned state.

### FR-2: Provider interaction

All provider operations shall use validated endpoint configuration and finite response/download budgets. Automatic retries are restricted to reviewed idempotent GET behavior. Side-effecting provider POST operations shall not gain implicit retry authority. Credentials and provider content shall not be copied into ordinary diagnostics.

### FR-3: Durable lifecycle and tenancy

The durable business identity is tenant-qualified where tenancy is enabled. `TenantDurableBatchAPIClient` shall validate its trusted host-selected `tenant_scope` synchronously at construction, before observation reservation, credential resolution, provider I/O, or lifecycle database I/O can occur. The tenant-qualified lifecycle key is `(tenant_scope, endpoint_alias, remote_batch_id)`; lifecycle persistence conflict targets, exact-row lookups, and operational status indexes shall retain `tenant_scope`, and package reads/writes shall bind that validated scope through parameterized transaction-local PostgreSQL context with forced row-level security for application roles. Provider/model content, endpoint aliases, remote identifiers, and transport data never select tenant authority.

The transaction-local `pg_llm_batch.tenant_scope` custom setting is routing context, not a credential or authenticated identity. Package code may set it only from a trusted authenticated/authorized host selection. A database role that can execute arbitrary SQL can still call `set_config` with an arbitrary tenant scope; the trusted application boundary must prevent generic tenant-controlled SQL, SQL injection, and incorrect identity mapping from selecting tenant authority. PostgreSQL RLS is defense in depth and does not replace those controls. PostgreSQL superuser/BYPASSRLS and arbitrary SQL access remain administrative escape hatches outside the tenant isolation guarantee.

The deployment credential provider remains a separate host/configuration authority: validating tenant scope before credential resolution does not make credentials tenant-keyed and does not authorize a tenant to select secrets.

Standalone source compatibility is also normative. `DurableBatchAPIClient` retains its four-argument lifecycle-recorder interface `(postgres_dsn, endpoint_alias, provider_batch, observation_order)`, and the default persistence/read helpers use the explicit `standalone` database scope rather than silently introducing a required tenant argument.

Protected-main acceptance authority for these invariants is deterministic: `tests/test_tenant_durable_client.py` proves construction-time pre-effect tenant validation and the four-argument standalone recorder seam; `tests/test_tenant_lifecycle_persistence.py` proves explicit `standalone` delegation, tenant-qualified conflict targets and reads, malformed-scope rejection before database access, and distinct tenant identities; `pg_llm_batch/schema.sql` supplies the tenant-qualified unique key, forced RLS policy, and tenant-qualified operational status index. `docs/remote-batch-lifecycle.md`, ADR 0002, and `docs/doctoring/tenant-scoped-lifecycle.md` describe the same protected-main contract.

### FR-4: Reconciliation and provider-effect recovery

Reconciliation shall be finite, deterministic, payload-free in its operational evidence, and use the same validated provider client boundary as normal operations. Candidate discovery, concurrency control, scheduling, and result-application semantics must be explicit capabilities rather than inferred from polling code. Provider-success/database-failure cases must remain observable recovery states rather than being rewritten as if the provider effect never occurred.

### FR-5: Persistence integrity and PostgreSQL recovery evidence

Package-owned database rows shall use descriptive two-or-more-word `snake_case` object names where applicable, explicit durable identities, parameterized SQL, and migrations that are idempotent or have a documented one-way boundary. Schema copies maintained for package and Docker initialization shall remain synchronized where the repository contract requires it. Malformed durable payload/state shall fail closed before downstream credential or provider effects when correctness depends on that state.

Protected main shall provide bounded, content-free recovery evidence without overstating its guarantee. `PostgresRecoveryReceipt` identifies one evidence set using package version, exact source commit, PostgreSQL major version, schema SHA-256, a reviewed backup-method vocabulary, backup-artifact SHA-256 and size, and bounded start/completion epochs. Backup-artifact inspection shall pin directory/file identity, reject symlink traversal and unsafe file shapes, remain within a caller-visible finite hashing budget, and return only hash/size evidence. Packaged-schema inspection shall stream the exact distributed `schema.sql` under a finite package-owned budget and return only hash/size evidence. Malformed, ambiguous, duplicate-member, hostile-subclass, oversized, mutating, unreadable, or cleanup-failing evidence shall fail closed through fixed package diagnostics.

These primitives do not execute `pg_dump` or `pg_restore`, persist backup bytes, prove backup provenance or restorability, prove a live-cluster schema matches the package, authorize a tenant/operator, manage encryption keys, manage WAL, establish PITR, or prove RPO/RTO/HA/DR/compliance. Executable logical backup/restore and isolated-restore acceptance remain separate governed capabilities. A future direct restore must make caller-owned source-superuser trust, target isolation, allowed libpq credential/service environment, transaction rollback behavior, and post-restore acceptance explicit before it can become protected-main truth.

### FR-6: Configuration and secrets

PostgreSQL-backed configuration and encrypted-secret support remain available for standalone use. Environment variables are bootstrap transport only where explicitly documented. Embedding hosts may inject credential providers without changing provider protocol semantics. The package shall not invent an external secret-management product dependency.

### FR-7: Observability and diagnostics

Operational telemetry is opt-in. Bounded operation/outcome vocabularies may be emitted; prompts, provider response bodies, credentials, arbitrary endpoint aliases, resource IDs, and arbitrary exception text are not telemetry attributes. Public readiness and ordinary errors shall use bounded categories when lower-layer text could contain sensitive data.

### FR-8: Standalone and modular deployment

The package shall remain usable without `contextual-orchestrator`, `naruon`, or another CWL repository. Host services may provide authentication, tenant routing, secret resolution, gateway/model routing, OpenTelemetry export, or scheduling, but those integrations shall not become hidden standalone requirements.

## Non-functional requirements

### Quality

Owned production Python must maintain exact 100% statement and branch coverage and complete public docstrings under the repository's configured gates. Supported validation includes Python 3.10, 3.12, and 3.14 plus realistic PostgreSQL/container integration where behavior depends on PostgreSQL.

### Security and privacy

Security-sensitive validation fails closed. Secrets, DSNs, prompt/provider content, unvalidated identifiers, and arbitrary lower-layer exception text must not be retained in logs or review evidence merely for debugging. Repository controls should support SOC 2 / CSAP evidence preparation without claiming certification.

The package must not apply blanket masking or lossy transformation to authorized business payloads merely because they contain PII: changing prompt, request, or result content can invalidate business meaning, token accounting, provider behavior, auditability, or downstream decisions. Authorized content fidelity is therefore a product requirement. Confidentiality controls belong at explicit boundaries instead: trusted host authentication/authorization and tenant selection, least-privilege database/service access, transport protection, deployment/storage protection where provided, purpose-limited retention and deletion, and package-owned logs/telemetry/errors that omit content-bearing values. Any content transformation must be an explicit host/business policy with provenance and acceptance evidence, not a hidden package default or a claim that redacted diagnostics mean persisted business data was masked.

### Reliability

Network, response, retry, wait, candidate-scan, payload, recovery-evidence, and release-evidence operations must be explicitly bounded. Recovery receipts and hashes are integrity/identity evidence, not restoration success. Recovery and rollback must be documented before migrations or release changes are considered complete. Queued, skipped, cancelled, absent, stale, predecessor-head, synthetic-merge-only, or infrastructure-failed evidence is not success for an exact source head.

### Interoperability

Provider interaction stays OpenAI-Batch-compatible behind a validated Python client seam. Embedding hosts can provide credentials and control-plane context without changing the package's durable/provider semantics. PostgreSQL backup/restore executors, when integrated, must remain caller-targeted infrastructure seams rather than hidden dependencies on a specific ContextualWisdomLab host.

### Packaging and release

Dependencies must be locked/reproducible according to repository policy. Release acceptance must include required quality, security, package/container, SBOM, provenance, artifact-identity, rollback/recovery, and governance evidence on the exact integrated protected head. A release is not implied by a version string or a successful pull request.

## Explicit non-goals

- Replacing host authentication or authorization.
- Treating PostgreSQL RLS as a credential or as SQL-injection prevention.
- Making provider payload/model output an authority for tenant or endpoint selection.
- Providing an unbounded general-purpose HTTP proxy.
- Reintroducing provider networking or independent scheduling inside PostgreSQL.
- Claiming a backup is restorable, a live cluster matches packaged schema, or a recovery objective is met from receipt/hash evidence alone.
- Claiming distributed exactly-once processing without an integrated transaction/recovery contract spanning every external effect.
- Requiring a specific ContextualWisdomLab host service for standalone operation.
- Claiming SOC 2, CSAP, or other certification solely from repository controls.

## Product acceptance boundary

A product capability moves to **IMPLEMENTED-ON-PROTECTED-MAIN** only after its unchanged source has satisfied the live ruleset, required exact-head CI/security/coverage/package/provenance/release checks, valid review findings are resolved, and the resulting tree is integrated into the protected default branch. Documentation must then be updated to move the capability out of `ACTIVE-PR`, `PARTIAL`, or `PLANNED`; historical evidence must not be transferred as if it were proof for a different head.
