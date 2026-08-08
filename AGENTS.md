# AGENTS.md

## Code-owner review gates — disabled (on hold)

As of 2026-08-04, code-owner review requirements (`require_code_owner_reviews` in branch
protection, `require_code_owner_review` in rulesets) are disabled across the ContextualWisdomLab
org: there is a single maintainer (solo developer), so a code-owner approval gate can never be
satisfied. This is ON HOLD until the org has multiple maintainers — do NOT re-enable these
settings or add CODEOWNERS-based merge gates before then.

## HTTP readiness confidentiality

- `check_health()` is the trusted local operator diagnostics surface and may contain diagnostic detail needed for troubleshooting.
- `serve_healthz()` must publish only `public_health_report()`, which allow-lists `ready`, `component`, and `is_ready` for the public readiness representation.
- Never serialize the detailed local report directly from `/healthz`, copy database exception text into the public readiness response, or widen that response without deterministic tests and a reviewed security contract.
- The PostgreSQL health-function query must retain its parameterized, transaction-local `statement_timeout`; do not replace it with a process- or server-global timeout setting or remove the bound without deterministic reliability tests and an explicit operator-contract review.
- `Cache-Control: no-store` is a caching control, not authentication; network exposure, ingress, and authorization remain deployment concerns.
