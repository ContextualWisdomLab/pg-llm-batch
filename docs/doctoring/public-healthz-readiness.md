# Public `/healthz` readiness confidentiality

## Purpose

`pg-llm-batch` deliberately separates **local operator diagnostics** from the network-facing **public /healthz** representation. This note is the authoritative operator contract for that boundary.

The package's `check_health()` function remains suitable for trusted local diagnosis. It can report database connection failures and PostgreSQL health-function **diagnostic detail** so an operator can understand why the service is not ready. The CLI may continue to print that detailed local report.

The HTTP endpoint is different. Probe clients need readiness state, not troubleshooting content. `/healthz` therefore projects each local component to only `component and is_ready`, plus the top-level `ready` boolean. Unknown top-level values, database exception strings, extension versions, internal hostnames, credentials, debug keys, SQL health-function `detail`, and future diagnostic fields are discarded before JSON serialization.

## Security rationale

MITRE **CWE-209** identifies externally visible error detail as an information-disclosure weakness because messages can reveal environmental or sensitive data. The fixed allow-list projection follows the same defensive principle: public output is constructed from the fields the probe contract needs rather than trying to enumerate every field that might become sensitive later.

This change is **not authentication**. It neither hides the existence of the endpoint nor authorizes callers. An operator who needs to prevent untrusted network access must still use deployment controls such as private networking, ingress rules, service-mesh policy, firewall policy, or an authenticated gateway where appropriate. The package's responsibility is narrower: if a caller can reach readiness, the response does not unnecessarily disclose local diagnostic detail.

## Probe and caching behavior

The endpoint keeps its existing readiness semantics:

- `200` when the local report says the service is ready;
- `503` when it is not ready; and
- `404` for unrelated paths.

Kubernetes documents HTTP readiness probes as a mechanism for determining whether a container is ready to receive traffic. The orchestrator needs probe success/failure; it does not require database exception text or extension troubleshooting details.

Every `/healthz` response also carries `Cache-Control: no-store`. Under **RFC 9111**, `no-store` instructs caches not to store the response. This is appropriate for rapidly changing readiness state and reduces reuse of stale probe JSON. `no-store` is a cache directive, not a secrecy or authorization guarantee.

## Standalone and embedded operation

The change does not alter PostgreSQL schema, migrations, provider requests, credentials, batch state, or MSA integration. Docker and Compose may continue to use `/healthz`. Embedded hosts can call `check_health()` for a trusted local operator surface, while external readiness consumers receive the redacted projection.

There is no new dependency on `contextual-orchestrator`, `naruon`, or another CWL service. The same package works independently and as an imported MSA component.

## Verification

Deterministic tests exercise both sides of the boundary:

1. local `check_health()` continues to include useful failure reasons;
2. the public projection copies only `ready`, `component and is_ready`;
3. secret-like text, internal hostnames, debug values, and unknown keys never appear in the serialized response;
4. the HTTP handler applies the projection rather than serializing the local report directly;
5. status-code and 404 behavior remain compatible; and
6. `Cache-Control: no-store` is present.

The normal quality gate must continue to prove 100% production statement and branch coverage, 100% public docstrings, compilation, lint, lock freshness, package construction, and container builds. Security and SAST checks remain mandatory. A generated pull-request merge ref is useful development evidence but is not final exact-source-head evidence under repository policy.

## Operator recovery

If `/healthz` reports `503`, use trusted **local operator diagnostics** such as `python -m pg_llm_batch health`, database administration tooling, and protected logs. Do not add detailed exception text back to the public endpoint as an incident shortcut.

## Rollback

No persistent data changes, database migrations, or external protocol state are introduced, so code **rollback** is mechanically straightforward. Reverting this change restores the former HTTP payload and therefore reintroduces the information-disclosure surface. If operational diagnosis is the reason for considering rollback, retain redaction and use the local diagnostic path instead.

## References

MITRE. (2026). *CWE-209: Generation of Error Message Containing Sensitive Information* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/209.html

Kubernetes Authors. (2026). *Configure liveness, readiness and startup probes*. Kubernetes Documentation. https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/

Fielding, R., Nottingham, M., & Reschke, J. (2022). *RFC 9111: HTTP caching* (STD 98). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9111.html
