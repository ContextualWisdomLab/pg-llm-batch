# ADR: Bounded provider HTTP trust and replay boundary

## Status and maturity

**IMPLEMENTED-ON-PROTECTED-MAIN.** This ADR records the provider-facing trust and resource contracts already present on protected main. ACTIVE-PR #71 further hardens HTTP 425 handling, permanent TLS/fingerprint classification, post-handoff replay prevention, and diagnostic vocabulary; those refinements are not treated as shipped here.

## Context and decision drivers

`pg-llm-batch` sends credentials and batch payloads to an OpenAI-compatible Files/Batches endpoint and consumes provider-controlled identifiers, statuses, headers, JSON, JSONL, timing guidance, and errors. The provider is necessarily outside the package trust boundary. A naïve client could leak credentials to an ambiguous destination, build follow-up paths from hostile identifiers, materialize unbounded responses, or retry a side effect after an uncertain transport outcome.

The product needs a deterministic HTTP boundary that is interoperable with OpenAI-compatible endpoints while remaining finite, confidentiality-aware, and explicit about which operations may replay.

## Alternatives considered

1. **Thin `aiohttp` wrapper with provider responses trusted by convention.** Rejected because it makes URL, identifier, body-size, and replay safety caller folklore rather than a product contract.
2. **Automatic retry of every network/status failure.** Rejected because side-effecting Files/Batches POST operations can be duplicated when the original outcome is unknown.
3. **Proxy/gateway-specific client logic.** Rejected because pg-llm-batch must remain provider-neutral and independently deployable.
4. **Validated, bounded OpenAI-compatible adapter with method-aware retry policy.** Chosen.

## Decision

`BatchAPIClient` treats provider networking as an untrusted boundary. It validates credential-bearing gateway URLs before use, validates remote resource identifiers and governed endpoint paths before constructing follow-up requests, applies finite request timeouts, bounds control-plane JSON and result/error downloads before full materialization, and uses strict decoding/parsing contracts.

Automatic retry is restricted to the reviewed idempotent GET acquisition failure/status classes and finite attempt/delay budgets. Side-effecting upload, batch-create, and cancellation POST requests are **single-attempt** by default. A new replay/idempotency mechanism requires a separate reviewed contract rather than being inferred from a generic retry helper.

Credentials authorize the outbound request. They do not make provider output trusted data, and provider payload text is not a safe diagnostic channel by default.

## Consequences and non-goals

- Some transient side-effecting failures surface to the caller instead of being invisibly retried.
- Provider integrations must satisfy the reviewed URL/path/identifier grammar and resource limits.
- The package gains bounded memory/time behavior and a stable distinction between read retry and write replay.
- The package does not claim provider authenticity beyond the configured TLS/credential boundary.
- The package does not claim that an accepted request was not processed merely because the response was lost.
- ACTIVE-PR #71 can tighten classifications without rewriting the protected-main baseline in this ADR until it integrates.

## Failure and recovery

Validation failures occur before the credential-bearing request when the relevant input can be checked locally. Retryable GET acquisition failures are retried only within the configured finite policy. Non-retryable transport/status failures surface as bounded package errors.

For side-effecting POST uncertainty, callers reconcile using provider/job identifiers and durable lifecycle evidence when available rather than blindly replaying. Result retrieval remains subject to bounded download/JSONL validation and closes responses according to the client ownership contract.

## Security, privacy, and governance impact

The URL/resource/path validation boundary reduces SSRF, credential-redirection, path-confusion, and uncontrolled follow-up-request risk. Response-size limits reduce memory/resource exhaustion. Diagnostics must not copy credentials, provider bodies, arbitrary endpoint aliases, or hostile dynamic provider messages merely to improve debuggability.

Deployment-level DNS, TLS trust store, egress firewall/service mesh, and provider contractual authorization remain host responsibilities unless a later accepted boundary explicitly moves them into the package.

## Compatibility and migration

Public HTTP behavior is part of `docs/product/API_CONTRACT.md` and Semantic Versioning discipline. Tightening validation may reject inputs that were previously accepted accidentally; such changes require explicit compatibility/security justification and regression coverage. Provider-specific extensions should be introduced through versioned adapter seams rather than by weakening the common boundary.

## Verification and acceptance

Acceptance requires deterministic destination/resource/path validation tests, bounded control-response/download tests, timeout/retry tests, confidentiality-safe error tests, and supported-version CI/security gates. Changes to replay semantics require tests proving the intended request count and delay behavior for both idempotent and side-effecting operations.

## Rollback and supersession

A regression may revert to the last protected-main HTTP contract only if the revert does not reintroduce a known credential, resource-bound, or replay weakness. This ADR is superseded only by a decision that explicitly defines destination authority, body/resource ceilings, retry/replay semantics, failure reconciliation, compatibility, and security evidence for the replacement transport model.