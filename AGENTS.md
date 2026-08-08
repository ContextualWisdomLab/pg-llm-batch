# AGENTS.md

## Code-owner review gates — disabled (on hold)

As of 2026-08-04, code-owner review requirements (`require_code_owner_reviews` in branch
protection, `require_code_owner_review` in rulesets) are disabled across the ContextualWisdomLab
org: there is a single maintainer (solo developer), so a code-owner approval gate can never be
satisfied. This is ON HOLD until the org has multiple maintainers — do NOT re-enable these
settings or add CODEOWNERS-based merge gates before then.

## Provider retry invariant

Automatic provider retries are restricted to idempotent GET operations. The reviewed default
HTTP status set is exactly `{408, 425, 429, 502, 503, 504}`; HTTP 425 `Too Early` uses the same
bounded `Retry-After` or equal-jitter delay path as the other statuses. Provider POST operations
remain single-attempt, and HTTP 500 is not retryable by default without a separately reviewed
provider-specific contract. Do not widen this replay boundary without deterministic regression
tests and authoritative protocol/security documentation.
