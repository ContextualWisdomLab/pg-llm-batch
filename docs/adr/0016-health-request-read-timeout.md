# ADR 0016: Health probes bound partial-request read time

- **Status:** Proposed
- **Date:** 2026-08-09
- **Decision owners:** ContextualWisdomLab maintainers
- **Extends:** ADR 0014

## Context

ADR 0014 bounded concurrent `/healthz` admission to 32 request workers so a connection flood cannot allocate unbounded threads or PostgreSQL checks. That ceiling alone does not bound how long an admitted client can occupy one of those finite admission slots.

Python's `BaseHTTPRequestHandler` parses the request line and headers before it dispatches `do_GET()`. Python 3.14 also warns that `http.server` is not recommended for production because it implements only basic security checks. A client that connects and then sends an incomplete request slowly can therefore hold a worker while the handler waits for more request bytes unless the accepted socket has a finite read timeout. Thirty-two such partial requests could consume all package-owned admission slots and deny legitimate readiness probes without exceeding the existing concurrency ceiling.

MITRE classifies availability loss caused by attacker-controlled resource occupancy as CWE-400, Uncontrolled Resource Consumption. The relevant package-owned resource here is not an unbounded number of workers—the prior ceiling already prevents that—but the duration for which an untrusted partial request may retain one finite worker slot.

## Decision

The generated `/healthz` request handler sets a **5-second request-read timeout** through the standard `StreamRequestHandler.timeout` contract inherited by `BaseHTTPRequestHandler`.

The timeout applies to accepted request-socket reads used to parse the HTTP request. It complements, and does not replace:

- the 32-request admission ceiling;
- the 5-second PostgreSQL connection timeout;
- the transaction-local 4,000 ms PostgreSQL `statement_timeout`;
- deployment-layer readiness probe deadlines; and
- ingress, firewall, service-mesh, or private-network controls.

A client that does not finish the request within this finite request-read window loses the connection and the request-thread `finally` path returns its admission slot. The timeout does not make `http.server` a general-purpose production HTTP server and does not expand the supported surface beyond this minimal readiness endpoint.

The package does not retry partial requests, preserve partial input, log attacker-controlled request content, or convert a request-read timeout into ready state. Legitimate orchestrator probes are expected to send their small GET request immediately after connecting; five seconds is deliberately longer than normal local-network request transmission while still bounding slow-client occupancy.

## Consequences

### Positive

- A slow or partial request cannot retain a finite admission slot indefinitely.
- The existing 32-worker ceiling becomes a bounded concurrency **and duration** contract rather than a bounded-count-only contract.
- The change does not add dependencies, schema, credentials, provider calls, or background writers.
- Existing 200/503 readiness semantics, response redaction, `Cache-Control: no-store`, SQL timeout, and runtime-fingerprint suppression remain unchanged.

### Trade-offs

- A client that takes more than five seconds to transmit the request line or headers is disconnected even if it would eventually complete.
- `http.server` remains intentionally limited to the minimal readiness role; deployments requiring a general public HTTP server should terminate traffic in a production-grade ingress or application server instead of widening this listener.
- Socket timeouts are not request-rate limits and do not replace deployment-level abuse controls.

## Verification

A production-boundary regression captures the handler class built by `serve_healthz()` and requires its socket-read timeout to equal `HEALTH_REQUEST_TIMEOUT_SECONDS`. Documentation contracts require both authoritative readiness documents to define the five-second timeout, partial-request threat, finite-slot recovery, and Python's production-use warning.

The full repository quality gate must continue to provide 100% production statement and branch coverage, 100% public docstrings, lint, package/container builds, security/SAST, and final exact-source acceptance after PR #88 integrates.

## Rollback

There is no data migration. Reverting the timeout restores indefinite admitted-socket read duration and therefore reopens slow-client exhaustion of the finite readiness worker pool. If five seconds proves incompatible with a legitimate deployment, change the reviewed constant with evidence rather than removing the bound.

## References

MITRE. (2026). *CWE-400: Uncontrolled Resource Consumption* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/400.html

Python Software Foundation. (2026). *http.server — HTTP servers*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/http.server.html

Python Software Foundation. (2026). *socketserver — A framework for network servers*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/socketserver.html
