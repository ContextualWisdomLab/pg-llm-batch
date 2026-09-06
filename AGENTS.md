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
- Keep PostgreSQL row-level security enabled and forced. Application connections
  must remain `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`
  across both effective `CURRENT_USER` and authenticated `SESSION_USER`
  authority. Admission must include every role the session user can select
  through `SET ROLE` or make selectable through membership administration; a
  safe-looking effective role is insufficient if the same login can later become
  an unsafe role. No role in that closure may own the lifecycle outbox, have
  exercisable/administerable owner authority via inherited `USAGE`, `SET ROLE`,
  or membership administration, hold PostgreSQL `CREATEDB`, `CREATEROLE`, or
  `REPLICATION`, hold `SELECT WITH GRANT OPTION` or `INSERT WITH GRANT OPTION`
  on the table or any column, or hold `TRUNCATE`, `DELETE`, `UPDATE`, `TRIGGER`,
  or table/column `REFERENCES` authority on the outbox. A session identity also
  must not hold membership `ADMIN OPTION` over any role that carries outbox
  `SELECT`/`INSERT` directly, inherits it, or can reach a DML-bearing role
  through an all-`SET TRUE` membership path. Callable non-system-schema
  `SECURITY DEFINER` routines are likewise outside the runtime envelope when
  their owner can exercise forbidden authority through superuser, `CREATEROLE`,
  `REPLICATION`, or `BYPASSRLS` status, exact/inherited table ownership,
  `SELECT`/`INSERT` grant options, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`,
  or `TRIGGER`; or when the owner can redistribute through membership
  `ADMIN OPTION` a role that directly, or through an all-`SET TRUE` path, carries
  forbidden runtime/operator authority including `CREATEDB`. This executable
  authority check is transitive across user-schema `SECURITY DEFINER` routines:
  after admission enters one definer owner principal, it must also inspect every
  further definer owner that principal can invoke through schema `USAGE` plus
  routine `EXECUTE`, with cycle-safe closure rather than only direct caller
  visibility. PostgreSQL permits a role administrator to grant the administered
  role to a new principal even when the administrator's own membership is
  `INHERIT FALSE, SET FALSE`; the new principal can then use the granted role's
  selectable path after the definer returns. `SECURITY DEFINER` similarly
  executes with its owner's privileges, so a safe outer owner does not make a
  privileged nested definer safe. Direct runtime `CREATEDB` and `CREATEROLE` are
  database/role administration capabilities outside an application identity;
  callable `CREATEROLE` is rejected because it is executable within the definer
  boundary, while `CREATEDB` remains covered when membership administration can
  grant that authority onward for later invoker-context use. `REPLICATION` is
  separate cluster-level connection and replication-slot authority and must not
  be co-located with a tenant application identity either directly or through an
  executable definer; `SELECT`/`INSERT` grant options, DML-bearing role
  administration, and executable privileged definer authority are authorization
  capabilities rather than application DML; `TRUNCATE` is outside RLS;
  tenant-local `DELETE` or `UPDATE` violates the append-only durable-intent
  invariant; and `REFERENCES`/`TRIGGER` can install relation behavior outside the
  package DML contract. Inert membership alone is not a bypass. Re-prove live
  enabled/forced RLS, the sole canonical tenant policy identity/command/role
  scope, parser-normalized `USING`/`WITH CHECK` predicates and allowed catalog
  dependencies, and the complete effective/session-selectable authority envelope
  before tenant binding or outbox data SQL. A migration success record is
  point-in-time evidence and does not authorize later same-name policy, ACL,
  membership, routine, or role-authority drift. The normal runtime role needs
  only non-grantable `SELECT` and `INSERT` on the outbox. Replay serialization
  must use transaction-scoped advisory locking on the validated tenant/event
  identity rather than `SELECT ... FOR UPDATE`, so serialization never requires
  ambient row-mutation authority. Do not authenticate runtime connections as a
  database creator, role administrator, replication identity, DML delegator,
  privileged definer gateway, or other administrator and rely on `SET ROLE` or
  `SET SESSION AUTHORIZATION` as a downgrade; administrative, replication,
  grant-capable, membership-delegating, executable-privileged, and owner-capable
  login sessions are outside the application isolation guarantee.
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