# AGENTS.md

## Code-owner review gates — disabled (on hold)

As of 2026-08-04, code-owner review requirements (`require_code_owner_reviews` in branch
protection, `require_code_owner_review` in rulesets) are disabled across the ContextualWisdomLab
org: there is a single maintainer (solo developer), so a code-owner approval gate can never be
satisfied. This is ON HOLD until the org has multiple maintainers — do NOT re-enable these
settings or add CODEOWNERS-based merge gates before then.

## HTTP readiness confidentiality

- `check_health()` is the trusted local operator diagnostics surface and may contain diagnostic detail needed for troubleshooting.
- `serve_healthz()` must publish only `public_health_report()`, which exposes `ready` plus `component` and `is_ready` only for the fixed required-component allow-list; unrecognized component names remain local and must not cross the public HTTP boundary.
- Public readiness validation is non-coercive: any malformed readiness shape or non-boolean `ready`/`is_ready` must fail closed to HTTP 503 with an empty public component list; never use truth coercion at this boundary.
- Never serialize the detailed local report directly from `/healthz`, copy database exception text into the public readiness response, or widen that response without deterministic tests and a reviewed security contract.
- The PostgreSQL health-function query must retain its parameterized, transaction-local `statement_timeout`; do not replace it with a process- or server-global timeout setting or remove the bound without deterministic reliability tests and an explicit operator-contract review.
- `serve_healthz()` may process requests concurrently but must cap the listener at **32 admitted readiness requests**. Treat **excess connections** as fail-closed availability pressure: close them **before worker or database work** instead of allocating another readiness thread or PostgreSQL check.
- Always **release every admission slot** after request completion and when worker-thread startup fails; never turn `ThreadingMixIn` into an unbounded resource-allocation path. Do not raise or remove the ceiling without deterministic resource-pressure tests and an explicit ADR/operator-contract review.
- `Cache-Control: no-store` is a caching control, not authentication; network exposure, ingress, and authorization remain deployment concerns.
