# ADR: Endpoint-qualified tokenizer metadata authority

- **Status:** PLANNED — Issue #108
- **Implementation dependencies:** protected integration or proven successors of #53 and #87
- **Documentation authority:** ACTIVE-PR #93

## Context

Protected `main` stores tokenizer metadata in `llm_endpoint_models` under composite endpoint/model identity, but `get_model_metadata(dsn, model_id)` resolves by `model_id` alone and orders by `last_verified_at`. The same provider-facing model identifier can therefore exist on multiple endpoints with different tokenizer metadata, allowing recency on endpoint B to influence token counting for endpoint A.

A fresh audit also identified a second authority failure. `get_model_metadata()` catches generic exceptions, emits lower-layer exception text in a debug log, and returns `None`. That makes a database/schema/permission/connection **lookup failure** observationally equivalent to a successful authoritative result with **no matching metadata**. Callers can then enter the tokenizer fallback path after an operational failure rather than after an explicit compatibility decision.

The schema comment still attributes population of endpoint/model metadata to a `pg_cron` model-sync job even though the repository is independently retiring legacy direct-SQL network/scheduler authority. Documentation must not preserve an unsupported scheduler as architectural truth.

## Decision drivers

- tokenizer selection must follow the trusted endpoint/model authority used for the request;
- cross-endpoint ambiguity must never be resolved only by metadata recency;
- **no matching metadata** must remain distinct from **lookup failure**;
- a database failure **must not silently** become tokenizer fallback;
- diagnostics must remain bounded and confidential rather than reflecting DSNs, SQL text, provider content, model text, endpoint text, or arbitrary exception text;
- preserve a deterministic compatibility fallback only after an authoritative no-metadata decision;
- retain standalone and modular embedding behavior without hidden sibling-database access; and
- avoid racing #53 database/tenant authority or #87 token/resource ownership.

## Alternatives considered

### A. Keep the model-only query and choose the newest row

Rejected. `last_verified_at` is freshness metadata, not endpoint authority. A newer row on another endpoint cannot establish the tokenizer for the current endpoint.

### B. Fail closed on every missing metadata row

Rejected as a universal rule because protected-main compatibility currently permits `pg_tiktoken` model-name mapping when no repository metadata is intentionally present. That fallback can remain only after the lookup itself succeeded and the compatibility policy explicitly authorizes it.

### C. Bind metadata to trusted endpoint/model identity and classify lookup outcomes

Chosen. The eventual API must require or derive a validated endpoint identity, query the endpoint/model key deterministically, and expose separate internal outcomes for matching metadata, authoritative absence, ambiguity/inconsistency, and lookup failure. Only authoritative absence can enter a documented compatibility fallback.

## Decision

1. Issue #108 owns the PLANNED endpoint-qualified tokenizer metadata authority.
2. Tokenizer metadata that influences counting/packing is keyed by trusted validated endpoint plus model identity; provider payloads and free-form model text do not select endpoint authority implicitly.
3. Cross-endpoint rows with the same `model_id` are not interchangeable and are never selected merely by `last_verified_at` ordering.
4. A successful query with **no matching metadata** is a different state from **lookup failure** caused by database/schema/permission/connection/query faults.
5. A lookup failure **must not silently** return the same semantic result as absence and must not activate tokenizer fallback.
6. Exported and logged failure evidence uses fixed **bounded diagnostics**. It does not copy DSNs, SQL text, credentials, provider data, arbitrary lower-layer **exception text**, dynamic exception class names, or unvalidated model/endpoint strings merely for debugging.
7. The existing `pg_tiktoken` model-name fallback may remain only under a documented deterministic compatibility rule after authoritative absence, not after lookup failure or ambiguity.
8. The stale `pg_cron` model-sync claim must be removed or replaced by a real supported population boundary before release; this ADR does not invent a scheduler.

## Data model and compatibility

No new persistence is invented. The existing composite endpoint/model schema is the starting authority. The implementation may evolve API signatures or introduce an endpoint-qualified helper, but must define compatibility for existing callers of `get_model_metadata()` and `TokenCounter`. Any migration must preserve existing rows and make ambiguous legacy behavior explicit rather than silently selecting one endpoint.

## Security, privacy, and operability

The design prevents a database fault from being hidden as a fallback success and reduces error-message information disclosure. It preserves purpose-bound tokenizer metadata while minimizing diagnostics. Operators need a bounded signal that lookup failed and must be able to distinguish configuration/data absence from database unavailability without receiving the query, DSN, or arbitrary driver exception text.

## Verification and acceptance

Implementation must include realistic PostgreSQL RED→GREEN coverage for:

- two endpoints advertising the same `model_id` with different tokenizer metadata;
- deterministic endpoint-qualified selection;
- cross-endpoint ambiguity rejection;
- authoritative no-row compatibility fallback;
- database/schema/permission/query **lookup failure** that cannot become fallback;
- secret-like sentinels in lower-layer exception text proving diagnostic confidentiality;
- successful existing single-endpoint behavior;
- concurrent metadata updates where applicable;
- Python 3.10, 3.12, and 3.14;
- exact 100% owned production statement/branch coverage and public docstrings; and
- current security, SAST, packaging, provenance, exact-source, and live-policy gates.

## Failure, recovery, and rollback

Lookup failure fails the affected tokenization decision closed with a bounded package-domain diagnostic. Recovery repairs the database/configuration authority and retries from a fresh endpoint/model lookup. Rollback must not restore cross-endpoint recency selection or generic exception-to-`None` fail-open behavior. Existing metadata rows are preserved unless a separately reviewed migration proves safe transformation.

## References

MITRE. (2026). *CWE-209: Generation of error message containing sensitive information (Version 4.20).* https://cwe.mitre.org/data/definitions/209.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: Database roles.* https://www.postgresql.org/docs/18/user-manag.html

PostgreSQL Global Development Group. (2026). *PostgreSQL 18 documentation: System information functions and operators.* https://www.postgresql.org/docs/18/functions-info.html
