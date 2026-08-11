# ADR: Persisted virtual JSONL payload integrity

- **Status:** PLANNED — Issue #124
- **Documentation maturity:** ACTIVE-PR #93
- **Implementation baseline:** protected `main` does **not** yet enforce this decision
- **Decision owner:** pg-llm-batch persisted payload boundary

## Context

Protected `main` stores package-prepared upload content in `llm_batch_file_payloads.content JSONB`. The package-owned writer uses a JSON object containing the serialized JSONL text, and `load_virtual_payload()` later reconstructs the upload from that row.

The current read boundary is permissive. `_normalize_payload_content()` returns `content.get("text", "")` for mappings, accepts a bare string, and stringifies every other JSONB shape with `str(content)`. Consequently, corrupted, manually edited, migrated, or otherwise malformed package-owned persisted state can become an empty string or Python textual representation instead of being rejected. `BatchAPIClient._load_payload_bytes()` can then encode the reconstructed value for provider upload. The defect is therefore a local persistence-integrity problem before an external side effect, not merely a provider response-format problem.

Issue #98 separately owns malformed provider **response** control JSON. Issue #124 owns malformed persisted **request payload** reconstruction.

## Drivers

- fail closed before credential resolution and provider I/O when package-owned durable payload state is malformed;
- preserve exact byte identity for valid disk-free payloads;
- avoid silently converting arbitrary JSONB scalars/arrays/objects into provider request data;
- keep prompt/request content out of diagnostics, logs, telemetry, and exception chains;
- preserve standalone and embedding-host compatibility;
- make any schema migration safe for existing volumes rather than assuming historical rows already conform;
- retain finite parsing/memory behavior and the repository's exact 100% owned production statement/branch coverage requirement.

## Alternatives considered

### A. Keep permissive Python coercion

Rejected. `str()` is a representation convenience, not an integrity contract. It can turn a valid PostgreSQL JSONB value into text that is not valid JSONL and can hide persistence corruption until after the provider boundary is crossed.

### B. Validate only in the provider upload method

Partially useful but insufficient as the sole authority. It would protect one external effect, but other current or future consumers of `load_virtual_payload()` could still observe malformed durable state. Validation should live at the narrowest reusable persistence-reconstruction boundary, with the upload path retaining a defensive no-provider-I/O regression.

### C. Add only a PostgreSQL `CHECK` constraint

Rejected as the initial universal remedy. A constraint can prevent future malformed rows, but adding it to an existing installation without inspecting historical data can make upgrades fail or encourage destructive cleanup. It also cannot by itself validate every JSONL framing/content invariant contained in the text value.

### D. Define one canonical persisted shape, validate it on read, and consider a separately proven schema constraint

Chosen. The Python reconstruction boundary must fail closed on unsupported persisted shape before provider effects. A schema constraint may be added only with explicit existing-volume detection, migration, rollback/recovery, and package/container schema-mirror evidence.

## Decision

1. `llm_batch_file_payloads.content` has one canonical package-owned representation for new writes: a JSON object containing the JSONL text under the documented payload-text member used by the writer.
2. The read boundary shall reject unexpected top-level JSONB shapes. It shall not stringify lists, numbers, booleans, null, or unrelated objects into upload content.
3. The expected payload-text member shall be present and shall have the exact supported string type. Missing or malformed text is corruption, not an empty payload.
4. Reconstructed content shall satisfy the package's bounded JSONL framing contract before external provider I/O. The implementation must preserve valid multiline payload byte identity and newline semantics while rejecting malformed records through bounded package-domain errors.
5. Persisted-payload validation shall complete before gateway credential resolution and before any HTTP request. The regression must prove zero credential-provider calls and zero provider calls for malformed durable state.
6. Error messages, structured details, logs, telemetry, and exception links shall identify only a fixed/bounded failure class and validated non-content identity needed for recovery. Prompt/request JSONL content must not be reflected.
7. If a PostgreSQL `CHECK` constraint is later selected, it is a separate migration decision within Issue #124. Existing rows must be inspected first; incompatible data fails closed into operator remediation. No `DELETE`, coercive rewrite, or `DROP ... CASCADE` behavior is implied by this ADR.
8. The implementation must keep package and container schema copies synchronized when schema changes are introduced.

## Security, privacy, and governance impact

The payload can contain personal, confidential, or otherwise purpose-bound application content. Integrity validation must preserve the content needed for the authorized batch purpose; blanket masking is not an integrity mechanism. The security objective is to prevent malformed durable state from silently becoming a different outbound request while keeping content out of diagnostic channels.

A successful JSONB parse is not sufficient evidence that the value matches the package's application-level payload schema. PostgreSQL JSONB intentionally supports all JSON value kinds; pg-llm-batch must impose its narrower package contract explicitly.

## Failure and recovery

On malformed persisted payload state:

1. stop before credential/provider I/O;
2. return a bounded package-domain integrity/validation failure without payload content;
3. leave the stored row unchanged so an operator can inspect or restore it under deployment authorization;
4. do not synthesize an empty payload, coerce the value, or automatically delete/rewrite evidence;
5. after repair, rerun reconstruction and the intended operation from the same validated package identity.

If an added database constraint blocks an upgrade because historical rows do not satisfy the canonical shape, rollback must restore the prior schema without deleting payload evidence. Operator guidance must distinguish schema rollback from content remediation.

## Compatibility and migration

Valid rows written by the package must reconstruct byte-identically after the change. The implementation should first prove the actual historical writer representation using unit and PostgreSQL integration fixtures. A read-only validation phase is preferred before any constraint is made authoritative for existing volumes.

Issue #124 must not be implemented as a competing edit while #71 owns the provider-client upload surface and #87/#53 plus their dependent stack own overlapping database/resource/schema surfaces. Implementation starts from the then-current protected result after those owners integrate or are superseded.

## Verification and acceptance

Permanent regression evidence shall include at least:

- valid canonical payload reconstruction with exact text/byte identity;
- malformed top-level list, number, boolean, null, unrelated object, missing text member, and non-string text member;
- valid multiline JSONL and final-newline behavior;
- malformed JSONL framing/content according to the package's supported record contract;
- zero credential-provider and provider-network calls after malformed persistence is observed;
- bounded content-free exception/log/telemetry evidence;
- PostgreSQL integration against realistic persisted rows;
- migration/rollback and package/container schema identity if a database constraint is introduced;
- Python 3.10, 3.12, and 3.14;
- exact 100% owned production statement/branch coverage and public docstrings;
- current security/SAST/package/provenance and exact-source acceptance gates.

## Non-goals

- validating arbitrary host-owned JSON schemas unrelated to the package's batch request format;
- masking or deleting valid prompt/request content;
- treating PostgreSQL JSONB syntax validity as equivalent to application-level JSONL validity;
- reimplementing provider response validation owned by Issue #98;
- weakening provider upload validation or accepting arbitrary coercion for compatibility;
- claiming cryptographic integrity or tamper-proof storage without a separately accepted design.

## Rollback and supersession

A read-validation implementation can be rolled back by reverting the validation code while retaining all durable rows. A database constraint can be rolled back only through its reviewed migration path and without deleting nonconforming evidence. A future ADR may supersede this decision only if it preserves explicit persisted-shape authority, pre-provider fail-closed ordering, content-confidential diagnostics, existing-volume recovery, and deterministic acceptance evidence.

## References

Bray, T. (2017). *The JavaScript Object Notation (JSON) Data Interchange Format* (RFC 8259, STD 90). RFC Editor. https://doi.org/10.17487/RFC8259

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: JSON types*. https://www.postgresql.org/docs/18/datatype-json.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Constraints*. https://www.postgresql.org/docs/18/ddl-constraints.html
