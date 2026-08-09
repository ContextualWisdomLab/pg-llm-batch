# Public `/healthz` readiness confidentiality

## Purpose

`pg-llm-batch` deliberately separates **local operator diagnostics** from the network-facing **public /healthz** representation. This note is the authoritative operator contract for that boundary.

The package's `check_health()` function remains suitable for trusted local diagnosis. It can report database connection failures and PostgreSQL health-function **diagnostic detail** so an operator can understand why the service is not ready. The CLI may continue to print that detailed local report. Detailed local output is not permissive readiness evidence: each required component must be observed exactly once. Missing or duplicate required-component rows make the local report not ready while preserving the returned diagnostic rows for troubleshooting.

The HTTP endpoint is different. Probe clients need readiness state, not troubleshooting content. `/healthz` therefore exposes only the top-level `ready` boolean plus `component and is_ready` for names in the **fixed required-component allow-list**. Unrecognized component names stay available to trusted local diagnostics but are discarded at the HTTP boundary along with unknown top-level values, database exception strings, extension versions, internal hostnames, credentials, debug keys, SQL health-function `detail`, and future diagnostic fields.

## Security rationale

MITRE **CWE-209** identifies externally visible error detail as an information-disclosure weakness because messages can reveal environmental or sensitive data. The fixed required-component allow-list follows the same defensive principle: public output is constructed from the exact component identities and fields the probe contract needs rather than relaying arbitrary local names or trying to enumerate every field that might become sensitive later.

HTTP response metadata is part of the same public boundary. Python's `BaseHTTPRequestHandler` normally adds a `Server header` whose default value identifies the stdlib server and the running `Python version`. The `/healthz` handler therefore overrides response emission to omit that `Server header` while retaining the normal status line, `Date`, and explicitly reviewed readiness headers. This reduces passive runtime fingerprinting; it is not authentication and it does not claim to hide every network- or behavior-level implementation characteristic.

Public readiness validation is **non-coercive**. Any **malformed readiness** shape—including a non-boolean top-level `ready`, a non-list component collection, a non-object component record, a non-string component name, or a non-boolean `is_ready`—is replaced by the fixed empty not-ready projection and returned as **HTTP 503**. Duplicate observations for any required component are also ambiguous readiness evidence and fail closed. Validly shaped but unrecognized component names do not become public evidence and do not affect the required-component readiness decision. The endpoint never interprets string, numeric, container, or object truthiness as readiness evidence. This prevents malformed local state, duplicate required rows, arbitrary local component identities, or future schema drift from becoming false-ready or information-bearing public evidence.

This change is **not authentication**. It neither hides the existence of the endpoint nor authorizes callers. An operator who needs to prevent untrusted network access must still use deployment controls such as private networking, ingress rules, service-mesh policy, firewall policy, or an authenticated gateway where appropriate. The package's responsibility is narrower: if a caller can reach readiness, the response does not unnecessarily disclose local diagnostic detail.

## Probe, query, and caching behavior

The endpoint keeps its existing readiness semantics:

- `200` when the validated public projection says the service is ready;
- `503` when it is not ready or when readiness input is malformed; and
- `404` for unrelated paths.

Kubernetes documents HTTP readiness probes as a mechanism for determining whether a container is ready to receive traffic. The orchestrator needs probe success/failure; it does not require database exception text or extension troubleshooting details.

After PostgreSQL connection acquisition, `check_health()` applies a parameterized PostgreSQL `statement_timeout` of **4,000 milliseconds** with `set_config(..., true)` before invoking `pg_llm_batch_health_check()`. The `true` scope is **transaction-local**: the package does not change PostgreSQL server defaults and does not intentionally leave a session-wide timeout behind. PostgreSQL 18 documents `statement_timeout` as an execution limit for statements, which makes it the appropriate database-side bound for a health function that could otherwise remain active after a connection has already succeeded.

The 4,000-millisecond SQL ceiling is **not an end-to-end deadline** for `/healthz`. The existing connection timeout, application scheduling, JSON generation, socket handling, and the deployment's probe timeout are separate bounds. Operators should therefore treat this setting as a fail-closed database-statement limit, not as a complete request-latency service-level objective. If PostgreSQL cancels the health statement, the package follows the normal database-failure path: trusted local diagnostics may retain the exception detail, while the public representation remains redacted and not ready.

Every `/healthz` response also carries `Cache-Control: no-store`. Under **RFC 9111**, `no-store` instructs caches not to store the response. This is appropriate for rapidly changing readiness state and reduces reuse of stale probe JSON. `no-store` is a cache directive, not a secrecy or authorization guarantee.

## Standalone and embedded operation

The change does not alter PostgreSQL schema, migrations, provider requests, credentials, batch state, or MSA integration. Docker and Compose may continue to use `/healthz`. Embedded hosts can call `check_health()` for a trusted local operator surface, while external readiness consumers receive the redacted projection. The local CLI keeps diagnostic detail but returns not-ready when required-component identity is missing or duplicated, so detailed troubleshooting cannot override ambiguous required readiness evidence.

There is no new dependency on `contextual-orchestrator`, `naruon`, or another CWL service. The same package works independently and as an imported MSA component. The timeout is established per health transaction, so standalone and embedded callers do not need a PostgreSQL configuration migration.

## Verification

Deterministic tests exercise both sides of the boundary:

1. local `check_health()` continues to include useful failure reasons and fails closed when a required component is duplicated;
2. the public projection copies only `ready`, `component and is_ready` for the fixed required-component allow-list;
3. unrecognized component names, secret-like text, internal hostnames, debug values, and unknown keys never appear in the serialized response;
4. malformed readiness shapes, duplicate required-component observations, and non-boolean state fail closed to an empty not-ready projection;
5. the HTTP handler applies the validated projection rather than raw local-report truthiness when selecting HTTP 200 or HTTP 503;
6. status-code and 404 behavior remain compatible;
7. `Cache-Control: no-store` is present;
8. inherited `BaseHTTPRequestHandler` response behavior cannot reintroduce a stdlib/Python `Server header`; and
9. the parameterized transaction-local `statement_timeout` is set before the PostgreSQL health function executes.

The normal quality gate must continue to prove 100% production statement and branch coverage, 100% public docstrings, compilation, lint, lock freshness, package construction, and container builds. Security and SAST checks remain mandatory. A generated pull-request merge ref is useful development evidence but is not final exact-source-head evidence under repository policy.

## Operator recovery

If `/healthz` reports `503`, use trusted **local operator diagnostics** such as `python -m pg_llm_batch health`, database administration tooling, and protected logs. If local diagnostics show duplicate required-component rows, investigate the `pg_llm_batch_health_check()` contract or deployment schema rather than accepting either duplicate as authoritative. If local diagnostics contain an unrecognized component name, keep it on the trusted operator surface unless an explicit public-contract change reviews and adds that identity to the required set. If local diagnostics indicate malformed readiness data, treat that as a contract or integration defect rather than coercing the value into a boolean. If local diagnostics indicate a statement-timeout cancellation, investigate the health function's locks, database load, extension availability, and query execution rather than increasing or removing the timeout as a first response. Do not add detailed exception text, arbitrary local component identities, or a runtime-identifying `Server header` back to the public endpoint as an incident shortcut.

## Rollback

No persistent data changes, database migrations, or external protocol state are introduced, so code **rollback** is mechanically straightforward. Reverting this change restores the former HTTP payload and therefore reintroduces the information-disclosure surface. Reverting strict readiness validation would also reintroduce truth-coercion and duplicate-row false-ready risk. Reverting the component-name filter would allow newly introduced local component identities to cross the public boundary without explicit review. Restoring the default `BaseHTTPRequestHandler.send_response()` behavior would reintroduce the stdlib/Python `Server header` and expose the runtime `Python version`. Removing the transaction-local statement limit separately would restore an unbounded connected-query path. If operational diagnosis is the reason for considering rollback, retain redaction, the fixed required-component allow-list, the non-coercive public projection, duplicate-row rejection, runtime-fingerprint suppression, and the bounded SQL contract and use the local diagnostic path instead.

## References

MITRE. (2026). *CWE-209: Generation of Error Message Containing Sensitive Information* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/209.html

Kubernetes Authors. (2026). *Configure liveness, readiness and startup probes*. Kubernetes Documentation. https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/

Fielding, R., Nottingham, M., & Reschke, J. (2022). *RFC 9111: HTTP caching* (STD 98). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9111.html

PostgreSQL Global Development Group. (2026). *19.11. Client connection defaults*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/runtime-config-client.html
