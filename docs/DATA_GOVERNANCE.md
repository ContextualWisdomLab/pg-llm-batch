# Data Governance and Privacy Contract

- **Document maturity:** ACTIVE-PR on canonical documentation PR #93 until protected integration
- **Runtime truth:** protected `main` source/schema is authoritative; ACTIVE-PR overlays are not shipped behavior
- **Scope:** package-owned PostgreSQL state, provider-bound batch content, credentials, telemetry, operator diagnostics, and host/package responsibility boundaries

## 1. Purpose

`pg-llm-batch` processes content that can contain personal, confidential, regulated, or commercially sensitive data. This document defines the package-level data-governance boundary without pretending that the package can determine a host application's legal basis, retention schedule, data-residency policy, or authorization model.

The goal is to preserve business utility while reducing ambient disclosure. The package therefore does **not** apply blanket masking to prompts or provider results. Instead, hosts must use purpose-bound authorization and minimize which data enters the batch workflow, while the package constrains storage, transport, diagnostics, and telemetry at the boundaries it owns.

## 2. Data classification

| Class | Examples on protected main | Package handling boundary |
| --- | --- | --- |
| **Secret** | provider credential values in `com_secrets`; optional Fernet bootstrap key; DSNs when they contain credentials | Never log, export, or include in telemetry. Provider secrets are read only for the selected endpoint operation. Bootstrap secrets are host-injected and must not become durable diagnostics. |
| **Sensitive content** | `llm_requests.system_prompt`, `llm_requests.user_prompt`, `llm_requests.response_content`, `llm_requests.response_metadata`, `llm_batch_file_payloads.content`, `llm_jsonl_lines.line_text`, provider result/error bodies | May contain PII or confidential business content. Persist only because the batch workflow requires it; do not emit raw content into logs, metrics, traces, health responses, release evidence, or exception diagnostics. |
| **Sensitive identifiers / metadata** | `custom_request_id`, endpoint aliases, provider file/batch identifiers, `provider_metadata`, model identifiers, timestamps | Treat as potentially linkable metadata. Validate and bound identifiers before use. Do not assume an endpoint alias or provider identifier is tenant identity or authorization evidence. |
| **Operational public metadata** | package version, documented CLI/API names, bounded health status such as component readiness | May be exposed only through reviewed public/operator contracts. Public readiness must not include arbitrary database/provider diagnostics. |

Classification is about handling risk, not a legal conclusion. The embedding host remains responsible for deciding whether a concrete field is personal data, regulated data, confidential information, or otherwise subject to a specific policy.

## 3. Protected-main package-owned persistence

Protected `main` persists batch workflow state in PostgreSQL. Material content-bearing tables include `llm_requests`, `llm_batch_file_payloads`, and `llm_jsonl_lines`; remote lifecycle metadata is persisted in `llm_remote_batch_jobs`; configuration and secret values are stored in `com_config` and `com_secrets`.

The package-owned database is therefore not a metadata-only store. Operators must protect PostgreSQL as a sensitive workload database and apply encryption, backup, access-control, monitoring, and retention controls appropriate to the data supplied by the host application.

The package does not currently implement a universal retention or erasure scheduler on protected main. **Retention, legal hold, erasure timing, backup expiry, and residency are host-owned policy decisions** unless a future accepted ADR and implementation explicitly move part of that authority into this package. A host must not infer that rows are automatically deleted because a provider batch reaches a terminal state.

## 4. Host-owned authorization and purpose

The host application owns subject/user authorization, business purpose, consent/legal-basis decisions where applicable, and selection of which records may be sent to an external model provider. `pg-llm-batch` must not infer authorization from request text, provider metadata, endpoint aliases, remote resource IDs, HTTP headers, or model output.

For shared-service deployments, hosts should bind authorization before creating package work and carry only the minimum purpose-relevant content into the batch request. Where tenant-aware package features exist only on ACTIVE-PR branches, their status must remain explicit rather than being used as evidence that protected main already enforces tenant isolation.

## 5. Tenant boundary and ACTIVE-PR status

Protected main does not yet provide the tenant-qualified lifecycle/RLS boundary proposed by ACTIVE-PR #53. The `tenant_scope` contract and forced PostgreSQL row-level isolation remain **ACTIVE-PR** until that work integrates and is revalidated on protected main.

Even after integration, `tenant_scope` is a host-selected authorization input, not something derived from provider data. PostgreSQL RLS is a defense-in-depth storage boundary and does not replace host authentication, service identity, or purpose authorization. Application database roles used with tenant RLS must remain least privilege (`NOSUPERUSER`, `NOBYPASSRLS`) under the implementing contract.

## 6. Provider disclosure boundary

Submitting a batch intentionally discloses request content and required metadata to the configured OpenAI-compatible provider endpoint. The host is responsible for selecting an authorized provider/region/account and determining whether that disclosure is permitted for the intended purpose.

The package is responsible for its narrower transport boundary: validate configured destinations and resource identifiers, use reviewed TLS rules, keep side-effecting POST operations single-attempt unless a separately reviewed idempotency design changes that contract, and bound provider responses. **Provider-error confidentiality is not yet protected-main behavior at this documentation baseline.** ACTIVE-PR #71 changes Files upload, batch creation/status, output/error file download, and cancellation rejection so provider-controlled HTTP error JSON, free-text bodies, debug fields, and messages are not copied into package diagnostics/results; those changes remain ACTIVE-PR until integrated and revalidated on protected main.

The same ACTIVE-PR #71 boundary covers malformed successful provider responses: invalid UTF-8 or JSON on a nominally successful response must produce fixed bounded diagnostics and must not retain provider bytes/text or decoder/parser exceptions through exported exception `cause` or `context`. This is important because confidentiality can be lost through exception chaining even when ordinary log formatting is redacted.

The target package contract is to avoid reflecting raw provider response bodies into exported errors or logs. Until ACTIVE-PR #71 is protected, acquisition/release evidence must not describe that target as shipped solely because this documentation branch states it. Provider responses remain untrusted input, and successful TLS plus a valid provider response does not convert provider content into authorization instructions or a new package policy authority.

## 7. Credentials and secret authority

Provider credential values are secret data. The package must never log them, return them in health/readiness output, include them in OpenTelemetry attributes, or place them in release/test evidence. The optional Fernet key is also sensitive bootstrap material and must remain outside logs/source/images and other ambient diagnostics.

`com_secrets` supports Fernet-encrypted-at-rest storage when configured; the no-key fallback is base64-obfuscated local/dev behavior rather than encryption. Hosts needing stronger enterprise secret-management controls should inject credentials through the documented credential-provider seam instead of weakening package boundaries.

ACTIVE-PR #87 tightens the persisted-secret trust boundary. In the no-key path, Base64 alphabet/padding and decoded UTF-8 are strict; malformed persisted data fails with bounded `ConfigError` instead of being repaired, guessed, or reflected. With Fernet configured, a wrong Fernet key or invalid encrypted value likewise fails as bounded `ConfigError`. Neither path may retain stored ciphertext/plaintext nor the lower-level decoder/cryptography failure through exported exception `cause` or `context`. These are ACTIVE-PR protections until #87 or a successor integrates.

## 8. Telemetry and diagnostics

The protected-main opt-in OpenTelemetry path is package-owned only for bounded operation signals. Telemetry must not contain prompts, provider response bodies, credentials, DSNs, endpoint aliases, provider URLs, resource identifiers, or arbitrary provider/database messages. Prefer finite operation/outcome vocabularies and low-cardinality attributes.

Health/readiness and ordinary operator diagnostics follow the same principle: expose enough bounded information to operate the component, but never log or return raw prompt text or secret values. The stronger provider HTTP error redaction described in section 6 is **ACTIVE-PR #71**, not protected-main evidence at this baseline; exact release acceptance must verify its integrated behavior before claiming provider-error confidentiality as shipped.

## 9. Logging and evidence

Package-owned logs, CI output, review evidence, release artifacts, SBOM/provenance records, and incident summaries **must not log** secret values, prompt bodies, raw provider response bodies, or full DSNs containing credentials. Tests should use synthetic non-secret fixtures and should assert that error translation does not retain sensitive values through exception messages, causes, or contexts where those surfaces are externally observable.

When incident investigation requires sensitive source data, access and export are host-owned privileged operations. Preserve minimum necessary evidence, record purpose and actor through the host's audit system, and avoid copying raw content into immutable public build/review artifacts.

## 10. Retention, erasure, export, and backup

Protected main provides no general-purpose data-rights workflow. The host owns:

- retention duration for prompts, generated responses, lifecycle metadata, and backups;
- erasure/export requests and identity-to-record mapping;
- backup encryption and backup-expiry enforcement;
- legal hold or regulatory preservation decisions;
- region/data-residency placement; and
- privileged-access review.

Package migrations and rollback routines must preserve retained evidence unless an explicit, reviewed operation authorizes deletion. A downgrade or rollback is not permission to discard records that the host still has a duty or business need to retain.

## 11. Encryption and access control

Use encrypted transport to non-loopback provider endpoints and protect PostgreSQL with deployment-appropriate encryption and access controls. Package code should use least-privilege database roles and avoid granting broad database or workflow authority merely to simplify automation.

This repository does not claim that storage, backups, KMS, residency, or identity governance are solved by the Python package itself. Those controls belong to the deployment/embedding environment unless implemented and documented by a future accepted package contract.

## 12. Failure and incident behavior

Fail closed when a required secret, destination, resource identifier, tenant input under an applicable tenant contract, or bounded provider response is invalid. Do not replace an authorization failure with a fallback tenant/provider, and do not expose sensitive payloads while reporting the failure.

If a credential or sensitive content is exposed through logs/artifacts, treat it as an incident: revoke/rotate affected credentials, restrict further distribution, preserve bounded evidence, identify the exact source/artifact/run, and repair the disclosure boundary. Package rollback alone does not rotate credentials or erase already published logs.

## 13. Release and acquisition acceptance

For an exact release candidate, data governance is acceptable only when:

1. this document matches the protected schema/runtime and all ACTIVE-PR overlays remain correctly labeled;
2. package telemetry/log/error/health contracts do not expose secret or raw sensitive content beyond reviewed boundaries, including fresh protected-main proof of provider-error confidentiality if ACTIVE-PR #71 or a successor is part of the release candidate;
3. stored-secret decode/decrypt behavior has fresh bounded-error and exception-chain privacy evidence if ACTIVE-PR #87 or a successor is part of the release candidate;
4. provider destination/resource validation and response bounds pass their security tests;
5. deployment documentation states host ownership of authorization, purpose, retention, erasure, backup, and residency;
6. migrations/rollback do not silently destroy retained content/evidence; and
7. any new persisted field or emitted signal is classified and traced before release.

This is an engineering control contract, not a claim of legal compliance, certification, or fitness for a particular regulated use without the embedding organization's separate assessment.

## 14. Traceability

- Protected persistence: `pg_llm_batch/schema.sql`.
- Provider transport and response bounds: `pg_llm_batch/batch_api_client.py` and security/HTTP tests.
- Provider-error confidentiality target and current implementation owner: ACTIVE-PR #71 plus `docs/doctoring/http-425-too-early-retries.md`; it becomes protected-main evidence only after integration and fresh validation.
- Stored-secret malformed Base64/UTF-8 and wrong Fernet key target: ACTIVE-PR #87 plus its SecretStore tests/doctoring; it becomes protected-main evidence only after integration and fresh validation.
- Credential storage/provider seam: configuration/secret-store modules and `docs/product/API_CONTRACT.md`.
- Telemetry privacy boundary: `pg_llm_batch/observability.py` and `docs/doctoring/opentelemetry-operations.md`.
- Threats and trust boundaries: `docs/THREAT_MODEL.md`.
- Operational handling/recovery: `docs/OPERABILITY.md`.
- Release gate: `docs/RELEASE_ACCEPTANCE.md`.
- Capability maturity and active tenant work: `docs/DOCUMENTATION_FITNESS.md` and `docs/TRACEABILITY.md`.
