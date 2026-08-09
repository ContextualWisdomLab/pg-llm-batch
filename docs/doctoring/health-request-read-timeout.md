# Health request-read timeout doctoring

## Operational finding

The standalone `/healthz` listener already limits concurrent admission to 32 workers, but the prior handler left accepted request sockets without a package-owned read deadline. Because `BaseHTTPRequestHandler` parses the request line and headers before dispatching `do_GET()`, a client that connects and transmits only a partial request can occupy one finite admission slot while the server waits for more bytes. Repeating that pattern across the finite pool can deny legitimate readiness probes without exceeding the worker-count ceiling.

Python 3.14.6 explicitly states that `http.server` is not recommended for production and implements only basic security checks. The same documentation describes `BaseHTTPRequestHandler` as parsing a request and headers before method dispatch. The package therefore treats the stdlib listener as a narrowly scoped readiness implementation and adds the missing package-owned duration bound instead of assuming the standard library provides production-grade slow-client protection.

## Contract

Every generated readiness handler has a **5-second request-read timeout**. The timeout is applied through the inherited stream-request-handler socket timeout contract before request parsing. It bounds slow or partial request occupancy of a **finite admission slot**; it does not alter the health SQL's own 4,000 ms statement timeout, the PostgreSQL connection timeout, HTTP 200/503 semantics, redaction, cache controls, or the 32-request admission ceiling.

The timeout is intentionally fail-closed. A client that cannot finish transmitting the request line and headers within five seconds is disconnected. The request-thread finalizer still releases the admission slot. No partial request body or attacker-controlled text is logged or persisted by this feature.

## Threat and deployment boundary

MITRE CWE-400 describes uncontrolled resource consumption as an availability weakness when attacker-controlled work prevents legitimate users from accessing a service. Here the controlled resource is the lifetime of an already-bounded worker slot. The combination of a fixed worker count and a finite socket-read duration prevents an admitted slow client from holding that slot indefinitely.

This is not authentication, rate limiting, TLS termination, or a substitute for a production ingress. Deployments should still keep readiness behind the narrowest practical network boundary and use service-mesh, firewall, private-network, or ingress policy appropriate to the environment. Python's production-use warning remains applicable; the package does not generalize this listener into a public application server.

## Verification

The regression test calls the real `serve_healthz()` factory with a socket-free HTTP server double, captures the generated `BaseHTTPRequestHandler` subclass, and verifies that its timeout equals `HEALTH_REQUEST_TIMEOUT_SECONDS`. This reaches the production handler-selection path while remaining deterministic and independent of wall-clock sleeps.

The documentation gate separately requires authoritative ADR and doctoring evidence to preserve the five-second duration, the partial-request threat model, finite-slot recovery, and Python's production-use warning. Repository-wide CI still requires 100% production statement/branch coverage and public docstrings.

## Recovery and rollback

If legitimate readiness clients hit the five-second boundary, first verify ingress queueing, proxy behavior, network path latency, overloaded runners, and client request construction. Increase the reviewed timeout only with evidence that a legitimate small GET cannot be transmitted inside the current bound. Removing the timeout entirely is not an acceptable incident workaround because it restores indefinite finite-slot retention.

No schema or external state changes are involved. Reverting the code is mechanically simple but reopens the availability condition described above.

## References

MITRE. (2026). *CWE-400: Uncontrolled Resource Consumption* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/400.html

Python Software Foundation. (2026). *http.server — HTTP servers*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/http.server.html

Python Software Foundation. (2026). *socketserver — A framework for network servers*. Python 3.14.6 documentation. https://docs.python.org/3.14/library/socketserver.html
