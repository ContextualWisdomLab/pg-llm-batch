# ADR 0014: Public healthz exposes readiness without diagnostic detail

- **Status:** Proposed
- **Date:** 2026-08-08
- **Decision owners:** ContextualWisdomLab maintainers

## Context

The package has two different readiness consumers. The local CLI and operator tooling need **local operator diagnostics** from `check_health()`, including database or extension `detail` values that help explain why a deployment is not ready. The network-facing **public /healthz** endpoint only needs enough information for an orchestrator or load balancer to decide whether the service is ready.

Before this decision, `serve_healthz()` serialized the complete local report. A connection exception or PostgreSQL health-function message could therefore cross the HTTP boundary. That creates an unnecessary information-disclosure surface consistent with **CWE-209**, even when the HTTP status itself is correct.

Kubernetes readiness probes require a success or failure result; they do not require database exception strings, internal hostnames, extension versions, or other diagnostic detail. HTTP caching is also undesirable for readiness responses because a stored response can outlive the state it represents.

## Decision

`check_health()` remains the detailed local contract. It continues to return the overall `ready` value and component records that can contain diagnostic detail for the CLI and local operator diagnostics.

The **public /healthz** response is a separate projection. It exposes only:

- the top-level boolean `ready`; and
- for each observed component, `component and is_ready`.

Every other top-level or component field is dropped before JSON serialization. In particular, database exception text, SQL health-function `detail`, debug fields, credentials, provider-controlled extras, and future unreviewed diagnostic fields cannot cross the public readiness projection merely because they were added to the local report.

The response keeps the existing `200` when ready and `503` when not ready behavior. Other paths remain `404`. The endpoint adds `Cache-Control: no-store`, consistent with **RFC 9111**, so caches are instructed not to store readiness representations.

This boundary is **not authentication** and does not make an intentionally public probe private. Deployments still own network exposure, ingress policy, service-mesh policy, and any authentication required for other endpoints. Redaction minimizes the information available if `/healthz` is reachable; it is not an authorization mechanism.

## Compatibility and MSA boundary

Standalone operation is unchanged: Docker and Compose can continue probing `/healthz`, while `python -m pg_llm_batch health` retains detailed local diagnostics. Embedding applications can keep calling `check_health()` when their trusted operator surface needs detail. No database schema, migration, provider API, model credential, or cross-service dependency changes.

The public projection copies a fixed allow-list instead of deleting known sensitive keys. This is fail-closed for future diagnostic fields: new local fields remain private unless the public contract is deliberately reviewed and changed.

## Security and operational consequences

### Positive

- Database exception strings and internal diagnostic detail no longer cross the public HTTP readiness boundary.
- Readiness clients retain useful component state without receiving troubleshooting content.
- `Cache-Control: no-store` reduces the chance that stale readiness JSON is stored or reused by an HTTP cache.
- Local troubleshooting remains useful because the CLI path is not redacted.

### Trade-offs

- Remote probe consumers can no longer inspect detailed failure text directly from `/healthz`.
- Operators must use trusted local tooling or logs for detailed diagnosis.
- A network-visible health endpoint still reveals that the service exists and whether named components are ready; deployments requiring a narrower exposure boundary must enforce that outside this package.

## Verification

Deterministic tests prove that secret-like text, internal hostnames, provider-controlled extra keys, database details, and unknown top-level fields are absent from the public projection. Separate HTTP tests prove the same redaction is applied by `/healthz`, status semantics are preserved, and `Cache-Control: no-store` is emitted. Existing tests continue to prove that detailed local diagnostics remain available.

The production suite must retain 100% statement and branch coverage and 100% public docstrings. Synthetic-merge-only CI is not final exact-head merge evidence; the branch must later obtain required exact-source-head evidence under the repository's protected merge policy.

## Rollback

There is no persistent state or migration to reverse. A code rollback restores the former detailed HTTP payload immediately, so rollback is mechanically simple but reintroduces the confidentiality risk. During an incident, prefer retaining the redacted endpoint and using local operator diagnostics rather than restoring public diagnostic detail.

## References

MITRE. (2026). *CWE-209: Generation of Error Message Containing Sensitive Information* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/209.html

Kubernetes Authors. (2026). *Configure liveness, readiness and startup probes*. Kubernetes Documentation. https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/

Fielding, R., Nottingham, M., & Reschke, J. (2022). *RFC 9111: HTTP caching* (STD 98). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9111.html
