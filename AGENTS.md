# AGENTS.md

## Code-owner review gates — disabled (on hold)

As of 2026-08-04, code-owner review requirements (`require_code_owner_reviews` in branch
protection, `require_code_owner_review` in rulesets) are disabled across the ContextualWisdomLab
org: there is a single maintainer (solo developer), so a code-owner approval gate can never be
satisfied. This is ON HOLD until the org has multiple maintainers — do NOT re-enable these
settings or add CODEOWNERS-based merge gates before then.

## Tenant lifecycle security contract

- Preserve standalone operation under the exact `standalone` tenant scope and keep the existing four-argument lifecycle-recorder interface source compatible.
- Derive `tenant_scope` only from an authenticated and authorized host boundary. Provider metadata, remote identifiers, request payloads, transport headers, and endpoint aliases are never tenant authorities.
- Validate tenant context before observation reservation, credential resolution, provider I/O, or database I/O.
- Bind tenant context with parameterized, transaction-local `set_config`; every lifecycle lookup, conflict target, and operational index must be tenant-qualified.
- Keep PostgreSQL row-level security enabled and forced. Application roles must be `NOSUPERUSER NOBYPASSRLS`; administrative bypass identities are outside the application isolation guarantee.
- Migrations must restore forced RLS within the same atomic SQL statement that relaxes owner enforcement, preserve legacy rows under `standalone`, remain idempotent, and keep the packaged and Docker initialization schemas byte-for-byte identical.
- Maintain 100% production statement, branch, and public-docstring coverage with realistic tenant-isolation, migration, rollback, compatibility, and concurrency tests.
