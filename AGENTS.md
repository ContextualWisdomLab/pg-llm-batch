# AGENTS.md

## Code-owner review gates — disabled (on hold)

As of 2026-08-04, code-owner review requirements
(`require_code_owner_reviews` in branch protection and
`require_code_owner_review` in rulesets) are disabled across the
ContextualWisdomLab organization. There is currently one maintainer, so a
code-owner approval gate cannot be satisfied. Do not re-enable these settings or
add CODEOWNERS-based merge gates until multiple independent maintainers exist.

## Tenant lifecycle security contract

- Preserve standalone operation under the exact `standalone` tenant scope and
  keep the existing four-argument lifecycle-recorder interface source
  compatible.
- Derive `tenant_scope` only from an authenticated and authorized host boundary.
  Provider metadata, remote identifiers, request payloads, model output,
  transport headers, and endpoint aliases are never tenant authorities.
- Validate tenant context before observation reservation, credential
  resolution, provider I/O, or database I/O.
- Bind tenant context with parameterized, transaction-local `set_config`; every
  lifecycle lookup, conflict target, and operational index must be
  tenant-qualified.
- Treat the custom PostgreSQL setting as a trusted application boundary, not a
  credential. A role with arbitrary SQL can select an arbitrary tenant scope;
  do not expose the lifecycle application role through generic tenant-controlled
  SQL, and never describe RLS as a substitute for authorization or
  SQL-injection prevention.
- Keep PostgreSQL row-level security enabled and forced. Application roles must
  be `NOSUPERUSER NOBYPASSRLS`, must not own the lifecycle outbox, and must not
  have exercisable owner authority through inherited `USAGE`, `SET ROLE`, or
  membership administration. They also must not hold `TRUNCATE`, `DELETE`,
  `UPDATE`, `TRIGGER`, or table/column `REFERENCES` authority on the outbox:
  `TRUNCATE` is outside RLS; tenant-local `DELETE` or `UPDATE` violates the
  append-only durable-intent invariant; and `REFERENCES`/`TRIGGER` can install
  relation behavior outside the package DML contract. Inert membership alone is
  not a bypass. Re-prove live enabled/forced RLS, owner separation, and absence
  of those destructive or programming privileges before tenant binding or
  outbox data SQL. The normal runtime role needs only `SELECT` and `INSERT` on
  the outbox. Replay serialization must use transaction-scoped advisory locking
  on the validated tenant/event identity rather than `SELECT ... FOR UPDATE`,
  so serialization never requires ambient row-mutation authority.
  Administrative and owner-capable identities are outside the application
  isolation guarantee.
- Migrations must restore forced RLS within the same atomic SQL statement that
  relaxes owner enforcement, preserve legacy rows under `standalone`, remain
  idempotent, and keep the packaged and Docker initialization schemas
  byte-for-byte identical.
- Update the README, operator guide, architecture, ADR, doctoring, and CHANGELOG
  whenever tenant identity, role, migration, direct-SQL, or rollback contracts
  change.
- Maintain 100% production statement, branch, and public-docstring coverage with
  realistic tenant-isolation, migration, rollback, compatibility, and
  concurrency tests.

## Provider retry invariant

Automatic provider retries are restricted to idempotent GET operations. The
reviewed default HTTP status set is exactly `{408, 425, 429, 502, 503, 504}`;
HTTP 425 `Too Early` uses the same bounded `Retry-After` or equal-jitter delay
path as the other statuses. TLS handshake and certificate failures are never
retried automatically; a repeated request cannot repair peer identity or TLS
policy. Certificate fingerprint mismatches are never retried automatically for
the same peer-identity reason. Provider POST operations remain single-attempt,
and HTTP 500 is not retryable by default without a separately reviewed
provider-specific contract. Do not widen this replay boundary without
deterministic regression tests and authoritative protocol/security
documentation.