# ADR 0014: Public healthz exposes readiness without diagnostic detail

- **Status:** Proposed
- **Date:** 2026-08-08
- **Decision owners:** ContextualWisdomLab maintainers

## Context

The package has two different readiness consumers. The local CLI and operator tooling need **local operator diagnostics** from `check_health()`, including database or extension `detail` values that help explain why a deployment is not ready. The network-facing **public /healthz** endpoint only needs enough information for an orchestrator or load balancer to decide whether the service is ready.

Before this decision, `serve_healthz()` serialized the complete local report. A connection exception or PostgreSQL health-function message could therefore cross the HTTP boundary. That creates an unnecessary information-disclosure surface consistent with **CWE-209**, even when the HTTP status itself is correct. Arbitrary local component identifiers can also disclose topology or implementation detail even when their per-component diagnostic fields are stripped.

Kubernetes readiness probes require a success or failure result; they do not require database exception strings, internal hostnames, extension versions, arbitrary local component names, or other diagnostic detail. HTTP caching is also undesirable for readiness responses because a stored response can outlive the state it represents.

The HTTP server implementation itself can disclose runtime detail independently of the JSON body. Python's `BaseHTTPRequestHandler` normally emits a `Server header` identifying the stdlib server together with the running `Python version`. A public readiness endpoint does not need that implementation fingerprint.

The readiness query also needs a database-side execution bound. A PostgreSQL connection can be established successfully while `pg_llm_batch_health_check()` stalls on database work. A connection timeout alone does not bound an already-started SQL statement.

The original standalone endpoint also used the serial `HTTPServer`. A delayed database check therefore had to complete before the server could start another request, allowing one slow client or dependency to serialize otherwise independent readiness probes.

## Decision

`check_health()` remains the detailed local contract. It continues to return the overall `ready` value and component records that can contain diagnostic detail for the CLI and local operator diagnostics.

Before invoking `pg_llm_batch_health_check()`, `check_health()` sets PostgreSQL `statement_timeout` to **4,000 milliseconds** through parameterized `set_config(..., true)`. The `true` argument makes the setting **transaction-local**, so the package does not alter the PostgreSQL server default or leak a session-wide timeout to later work on a reused connection. PostgreSQL 18 documents `statement_timeout` as the statement-execution limit; the package applies it only to this health transaction.

This database-side limit is **not an end-to-end deadline** for the HTTP request. Connection acquisition retains its separate bounded timeout, process scheduling and HTTP handling add their own latency, and deployment probe timeouts remain operator controls. The contract is narrower: after a connection exists, the health SQL must not execute without a package-owned database-side bound. A timeout exception follows the existing local-diagnostic failure path, and the public endpoint still returns only its redacted readiness projection.

The standalone listener uses a narrow `_ThreadingHealthHTTPServer` that combines `ThreadingMixIn` with `HTTPServer` and enables daemon request threads. Independent readiness probes can therefore begin concurrently when another probe is delayed, rather than being serialized by the server loop. This changes only request scheduling; the same bounded database check, redaction, status, path, header, and shutdown-process contracts remain authoritative.

The **public /healthz** response is a separate projection. It exposes only:

- the top-level boolean `ready`; and
- `component and is_ready` for identities in the **fixed required-component allow-list**.

Every other top-level or component field is dropped before JSON serialization, and validly shaped but unrecognized component names are omitted from the public representation. In particular, database exception text, SQL health-function `detail`, arbitrary local component identities, debug fields, credentials, provider-controlled extras, and future unreviewed diagnostic fields cannot cross the public readiness projection merely because they were added to the local report.

The HTTP response metadata follows the same minimum-disclosure rule. The handler overrides the inherited `BaseHTTPRequestHandler` response path so no default `Server header` containing the stdlib identity or `Python version` is emitted. It retains the status line, `Date`, and the explicitly reviewed readiness headers. This is fingerprint reduction, not authentication or a claim that the implementation is unidentifiable through every other channel.

Public readiness validation is **non-coercive**. Any **malformed readiness** shape—including a non-boolean top-level `ready`, a non-list `components`, a non-object component record, a non-string component name, or a non-boolean `is_ready`—fails closed to the fixed `{"ready": false, "components": []}` projection and **HTTP 503**. String, numeric, container, or object truthiness is never accepted as readiness evidence. Validly shaped unrecognized names are ignored rather than promoted to public probe output; they neither satisfy nor invalidate the fixed required-component set.

The response keeps the existing `200` when ready and `503` when not ready behavior. Other paths remain `404`. The endpoint adds `Cache-Control: no-store`, consistent with **RFC 9111**, so caches are instructed not to store readiness representations.

This boundary is **not authentication** and does not make an intentionally public probe private. Deployments still own network exposure, ingress policy, service-mesh policy, and any authentication required for other endpoints. Redaction minimizes the information available if `/healthz` is reachable; it is not an authorization mechanism.

## Compatibility and MSA boundary

Standalone operation is unchanged: Docker and Compose can continue probing `/healthz`, while `python -m pg_llm_batch health` retains detailed local diagnostics. Embedding applications can keep calling `check_health()` when their trusted operator surface needs detail. No database schema, migration, provider API, model credential, or cross-service dependency changes.

The public projection copies a **fixed required-component allow-list** instead of deleting known sensitive keys or relaying arbitrary local component names. This is fail-closed for future diagnostic fields and identities: new local fields and component names remain private unless the public contract is deliberately reviewed and changed. Malformed or unexpectedly typed readiness fields also remain fail-closed rather than being converted through Python truth coercion.

The transaction-local timeout likewise requires no schema or server-configuration migration. It is scoped to the current health transaction and rolls back automatically with that transaction. Concurrent request handling remains an implementation detail behind the same blocking `serve_healthz()` entrypoint, so callers and container probes need no protocol change.

## Security and operational consequences

### Positive

- Database exception strings, arbitrary local component identities, and internal diagnostic detail no longer cross the public HTTP readiness boundary.
- The default stdlib/Python `Server header` is not emitted, reducing passive runtime fingerprint disclosure.
- Readiness clients retain the fixed required-component state without receiving troubleshooting content.
- Malformed readiness values cannot become false-ready HTTP evidence through truth coercion.
- New local diagnostic component names do not silently widen the public interface.
- `Cache-Control: no-store` reduces the chance that stale readiness JSON is stored or reused by an HTTP cache.
- Local troubleshooting remains useful because the CLI path is not redacted.
- A connected but stalled PostgreSQL health statement receives a deterministic database-side execution ceiling instead of relying only on an outer probe timeout.
- Concurrent daemon request handling prevents one delayed probe from making the listener serially unavailable to independent readiness probes.

### Trade-offs

- Remote probe consumers can no longer inspect detailed failure text or optional/unrecognized local component names directly from `/healthz`.
- Operators must use trusted local tooling or logs for detailed diagnosis.
- A network-visible health endpoint still reveals that the service exists and whether the fixed required components are ready; suppressing one `Server header` does not make the implementation anonymous or replace network access control.
- Unexpected local health-report schema drift is intentionally reported as not ready rather than partially projected, while validly shaped unknown component identities are kept local.
- The 4,000-millisecond statement limit can classify unusually slow health-function execution as not ready even when it would eventually complete; that is intentional fail-closed readiness behavior, not a query-performance retry mechanism.
- Thread-per-request handling consumes bounded process resources per simultaneous probe; deployments must still apply appropriate network exposure and probe-frequency controls.

## Verification

Deterministic tests prove that secret-like text, internal hostnames, provider-controlled extra keys, database details, unknown top-level fields, and unrecognized component names are absent from the public projection. Separate HTTP tests prove the same redaction is applied by `/healthz`, status semantics are preserved, `Cache-Control: no-store` is emitted, and inherited `BaseHTTPRequestHandler` behavior cannot reintroduce a stdlib/Python `Server header`. Existing tests continue to prove that detailed local diagnostics remain available.

A malformed-readiness matrix proves that coercive top-level state, non-list component containers, non-object records, non-string component names, and non-boolean component readiness all produce the same empty not-ready public projection. A dedicated HTTP regression proves that this sanitized projection—not raw local-report truthiness—controls the 200/503 status decision. A separate allow-list regression proves that a valid but unrecognized local component identity is not serialized and cannot alter required-component readiness.

A focused reliability regression records SQL calls and requires the parameterized, transaction-local `statement_timeout` assignment to occur before the health function. A separate server regression verifies that the instantiated listener includes `ThreadingMixIn`, so independent readiness probes are not routed through the former serial request scheduler. Documentation contracts preserve the exact 4,000-millisecond boundary, the PostgreSQL 18 basis, the fixed required-component allow-list, the explicit `Server header`/`Python version` fingerprint boundary, and the explicit statement that the SQL timeout is not an end-to-end deadline.

The production suite must retain 100% statement and branch coverage and 100% public docstrings. Synthetic-merge-only CI is not final exact-head merge evidence; the branch must later obtain required exact-source-head evidence under the repository's protected merge policy.

## Rollback

There is no persistent state or migration to reverse. A code rollback restores the former detailed HTTP payload immediately, so rollback is mechanically simple but reintroduces the confidentiality risk. Reverting the non-coercive projection would also reopen the false-ready boundary for malformed state. Reverting the component-name filter would allow future local component identities to cross the HTTP boundary without deliberate review. Restoring the default `BaseHTTPRequestHandler.send_response()` behavior would reintroduce the stdlib/Python `Server header` and expose the runtime `Python version`. Removing the transaction-local statement bound would restore the unbounded connected-query behavior. Removing `ThreadingMixIn` would restore serial request handling, allowing one delayed readiness check to block independent readiness probes. During an incident, prefer retaining redaction, the fixed required-component allow-list, strict projection validation, runtime-fingerprint suppression, concurrent request handling, and the bounded SQL path while using local operator diagnostics rather than restoring public diagnostic detail or weakening the execution ceiling.

## References

MITRE. (2026). *CWE-209: Generation of Error Message Containing Sensitive Information* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/209.html

Kubernetes Authors. (2026). *Configure liveness, readiness and startup probes*. Kubernetes Documentation. https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/

Fielding, R., Nottingham, M., & Reschke, J. (2022). *RFC 9111: HTTP caching* (STD 98). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9111.html

PostgreSQL Global Development Group. (2026). *19.11. Client connection defaults*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/runtime-config-client.html

Python Software Foundation. (2026). *http.server — HTTP servers*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/http.server.html
