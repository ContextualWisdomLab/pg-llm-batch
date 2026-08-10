# pg-llm-batch Public API, CLI, and Schema Compatibility Contract

- **Document maturity:** ACTIVE-PR on the canonical documentation branch until protected integration
- **Protected-main baseline:** `bf2cc2e140dc3ff4a56c3203f80f41bb9fed5d10`
- **Package version on that baseline:** `0.1.0`

## 1. Purpose and authority

This document defines the compatibility surface that pg-llm-batch consumers may rely on. It separates **IMPLEMENTED-ON-PROTECTED-MAIN** interfaces from **ACTIVE-PR** targets so an open branch is never silently promoted to shipped API.

Runtime source remains the immediate authority if this document and protected code disagree. A disagreement makes this document stale and requires repair; it does not authorize callers to infer undocumented behavior.

## 2. Versioning policy

pg-llm-batch follows Semantic Versioning for published package releases. Before a stable 1.0 release, minor releases may introduce reviewed additive capability and explicitly documented breaking changes; patch releases must not intentionally break documented public behavior. Once 1.0 is reached, incompatible public API, CLI, or schema changes require a major version unless a separately documented compatibility policy explicitly permits otherwise.

A source commit, pull request, green check, or `Unreleased` CHANGELOG entry is not itself a published version.

### Deprecation

A public interface scheduled for removal must first be documented as deprecated with:

1. the replacement interface or reason no replacement exists;
2. the earliest release in which removal may occur;
3. migration guidance;
4. tests that preserve the deprecated behavior during the compatibility window; and
5. CHANGELOG coverage.

Security fixes may require an accelerated incompatibility when preserving old behavior would retain an exploitable boundary. Such a change requires an ADR or equivalent release decision and explicit operator migration guidance.

## 3. Python package surface — IMPLEMENTED-ON-PROTECTED-MAIN

The protected baseline exports the following names from `pg_llm_batch` and treats them as the documented package-root interface:

- `BatchAPIClient`
- `DurableBatchAPIClient`
- `GatewayCredentials`
- `config_credentials_provider`
- `PostgresConfigStore`
- `SecretStore`
- `get_config_store`
- `PgLlmBatchError`
- `ConfigError`
- `GatewayError`
- `TokenLimitExceededError`
- `ValidationError`
- `BatchRequest`
- `ModelMode`
- `BatchPayload`
- `PostgresBatchOrchestrator`
- `BatchAccumulator`
- `TokenCounter`
- `__version__`

Public names added only by an ACTIVE-PR remain target interfaces until their implementing branch reaches protected main and the package-root export contract is revalidated.

### Python error compatibility

Callers may depend on the documented package exception hierarchy for domain failures, but they must not parse free-form exception messages as a stable machine protocol unless a specific structured field is documented. Provider-controlled bodies, credentials, DSNs, and other confidential values are not part of the public error contract.

### ACTIVE-PR `BatchRequest` runtime boundary (#104)

`BatchRequest` is public on protected main, but exact runtime field typing is an **ACTIVE-PR** compatibility hardening until #104 integrates. The target requires `user_prompt`, `model`, and `id` to already be exact strings and `system_prompt` to be `None` or an exact string; it does not stringify non-string caller objects or reinterpret false-valued non-strings as empty content. Rejected values must not be exported through the resulting package validation message or structured details. Empty strings remain accepted for compatibility, and prompt/model content-policy validation remains host/provider-owned rather than being inferred by this lightweight record. This paragraph must be promoted to protected-main behavior only after the implementing source is integrated and revalidated there.

### Resource ownership

Objects that acquire PostgreSQL connections, HTTP sessions, files, iterators, or other finite resources must expose and document deterministic ownership/closure behavior. ACTIVE-PR changes that harden cleanup do not become the protected-main contract until merged.

## 4. CLI surface — IMPLEMENTED-ON-PROTECTED-MAIN

The baseline `python -m pg_llm_batch` / console entry point provides:

- `init-db`
- `config set`
- `config get`
- `config set-secret`
- `count-tokens`
- `submit`
- `poll`
- `wait`
- `retrieve`
- `health`
- `serve-healthz`

Command names, required option names, exit-code meaning, and structured JSON output documented in README/operability guidance are compatibility surfaces. Human-readable incidental wording is not a machine protocol unless explicitly declared.

### ACTIVE-PR CLI overlays

Current active changes include stronger secret input, connection ownership, listener defaults, bootstrap-source precedence, and related security behavior. They remain ACTIVE-PR until protected integration.

Issue #90 tracks a **PLANNED** `cancel` operator command that would reuse the existing provider cancellation primitive. It is not currently part of the shipped CLI contract.

## 5. Provider HTTP contract

`BatchAPIClient` targets an OpenAI-compatible Files/Batches shape while enforcing package-specific validation and resource limits. Compatibility means pg-llm-batch preserves its documented call/result semantics and validated identifiers; it does not promise compatibility with every undocumented provider extension.

Side-effecting provider requests are not automatically replayed merely because a transport failed. Idempotent retry behavior, timeout bounds, response limits, and response-handoff ownership are normative technical requirements in the TRD and are part of the behavior contract for the release in which they are implemented.

## 6. PostgreSQL schema contract

`pg_llm_batch/schema.sql` is the canonical protected-main package schema for the baseline. Docker initialization mirrors that schema where the repository explicitly requires byte identity. Package-owned objects use descriptive snake_case names and explicit constraints.

Schema compatibility rules:

1. A migration must identify its forward effect and rollback/recovery boundary.
2. Existing retained data must not be silently re-parented, truncated, or dropped to simplify an upgrade.
3. An additive table/column/index is not considered deployed merely because an ACTIVE-PR contains it.
4. A destructive or semantically incompatible schema change requires migration guidance, compatibility tests, and explicit release acceptance.
5. PostgreSQL object ownership, RLS, privilege, trigger, transaction, and isolation assumptions are security-relevant API semantics, not incidental implementation details.

### Current protected persistence

The baseline includes the current core/config/lifecycle schema documented in `docs/architecture/ERD.md`, including `llm_remote_batch_jobs`.

### ACTIVE-PR persistence overlays

Tenant-qualified lifecycle/RLS, result checkpoints, checkpoint accepted-save audit records, and related migration/operator behavior remain ACTIVE-PR until their exact stack reaches protected main. Conceptual ERD entries must remain labelled accordingly.

## 7. Data-format and evidence compatibility

Versioned persisted or externally exchanged structures must carry enough information to refuse incompatible reinterpretation. Examples include checkpoint schema versions, audit manifest framing versions, release evidence descriptors, and future versioned API/event envelopes.

A cryptographic digest used for deterministic identity does not automatically become a signature, attestation, authentication mechanism, or release authority. Those semantics require their own versioned contract and trust boundary.

## 8. Standalone and MSA compatibility

The package must remain independently usable without requiring naruon, contextual-orchestrator, or another ContextualWisdomLab service. CWL integrations should consume stable public interfaces rather than another service's application database or unversioned internal modules.

Hosts remain responsible for authentication-to-tenant mapping, ingress, higher-level authorization, service identity, durable cross-system workflow coordination, external secret infrastructure, deployment topology, and any stronger audit-retention system not explicitly owned by pg-llm-batch.

## 9. Change classification

A proposed change is **additive** when an existing documented caller continues to work without behavioral reinterpretation. It is **compatible-hardening** when it rejects behavior that was already invalid/unsafe under the documented contract. It is **breaking** when a previously documented valid call, result, schema use, or operator workflow can no longer be used as documented.

When classification is ambiguous, treat the change as potentially breaking until a regression test and compatibility analysis prove otherwise.

## 10. Acceptance evidence

A public contract change is accepted only when:

- the implementation is present on the exact source head under review;
- realistic compatibility tests exercise the public boundary;
- documentation and CHANGELOG agree with the implementation maturity;
- migration/rollback guidance exists where persistence is affected;
- security and resource-ownership consequences are tested;
- required CI/review/security gates pass on the unchanged final head; and
- protected-main integration is verified before the maturity is changed to IMPLEMENTED-ON-PROTECTED-MAIN.

Synthetic merge checks, predecessor-head runs, status-only reviews, or an open PR are not substitutes for those authorities.

## 11. References

Preston-Werner, T. (n.d.). *Semantic Versioning 2.0.0*. https://semver.org/spec/v2.0.0.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/
