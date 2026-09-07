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
  an unsafe role. A pure `SET TRUE` path does not mint membership: the intended
  non-grantable outbox `SELECT`/`INSERT` on an ordinary SET-selectable forced-RLS
  application role remains valid. The delegated-DML authority envelope begins
  only after an `ADMIN OPTION` edge is crossed; that ADMIN-bearing state must be
  preserved recursively through any later `SET` or `ADMIN` edge. No role in the
  direct selectable closure may own the lifecycle outbox, have exercisable/
  administerable owner authority via inherited `USAGE`, `SET ROLE`, or membership
  administration, hold PostgreSQL `CREATEDB`, `CREATEROLE`, or `REPLICATION`, hold
  `SELECT WITH GRANT OPTION` or `INSERT WITH GRANT OPTION` on the table or any
  column, or hold `MAINTAIN`, `TRUNCATE`, `DELETE`, `UPDATE`, `TRIGGER`, or table/
  column `REFERENCES` authority on the outbox. A session identity also must not
  hold membership `ADMIN OPTION` over any role that carries outbox `SELECT`/
  `INSERT`/`MAINTAIN` directly, inherits it, or can reach such authority through
  recursively mixed `SET`/`ADMIN` membership edges. Callable non-system-schema
  `SECURITY DEFINER` routines are likewise outside the runtime envelope when
  their owner can exercise forbidden authority through superuser, `CREATEROLE`,
  `REPLICATION`, or `BYPASSRLS` status, exact/inherited table ownership,
  `SELECT`/`INSERT` grant options, `MAINTAIN`, `TRUNCATE`, `DELETE`, `UPDATE`,
  `REFERENCES`, or `TRIGGER`; or when the owner can redistribute through membership
  `ADMIN OPTION` a role that directly, or through a recursively mixed `SET`/`ADMIN`
  path, carries forbidden runtime/operator authority including `CREATEDB` or
  `MAINTAIN`. Do not bound delegated-definer authority to one administered role
  plus one all-SET layer. This executable authority check is transitive across
  user-schema `SECURITY DEFINER` routines: after admission enters one definer owner
  principal, it must also inspect every further definer owner that principal can
  invoke through schema `USAGE` plus routine `EXECUTE`, with cycle-safe closure
  rather than only direct caller visibility. Every callable routine in that closure
  must also pin its routine-level `search_path = pg_catalog, pg_temp`; absent or
  different name-resolution authority is rejected before tenant binding or outbox
  data SQL, rather than trusting caller temporary-schema state or unqualified user-
  schema objects. The callable definer owner itself must also pass the same reachable
  ordinary-view, materialized-copy, inheritance/partition, and opaque foreign-data
  authority probe as a runtime principal. A caller's missing direct `SELECT` on a
  foreign relation is not evidence of safety when a callable definer executes with an
  owner that has that relation authority through its own foreign-server/user-mapping
  context. Do not parse one current routine body to allowlist that owner capability.
  Caller-selectable ordinary views are a second executable authority graph: admission
  must follow the cycle-safe view dependency closure from every view the runtime can
  select, applying PostgreSQL's effective principal at each edge—the invoking runtime
  principal for a `security_invoker=true` view and otherwise the current view owner.
  Any reachable non-security-invoker view that directly reads the lifecycle outbox is
  outside the runtime envelope when its owner is a superuser or `BYPASSRLS` principal
  with outbox read authority. PostgreSQL otherwise applies that view owner's
  permissions and RLS policies to the underlying relation, so a safe outer view can
  hide a privileged inner view and expose cross-tenant rows even when the runtime
  caller itself is `NOBYPASSRLS`; reject the complete reachable path before tenant
  binding or outbox data SQL. Caller-readable materialized views are a distinct
  copied-data authority graph: PostgreSQL returns their stored rows directly rather
  than applying the defining query and source-table RLS at read time. Admission must
  therefore include materialized relations reached directly by the runtime or
  indirectly through ordinary views and follow each reachable materialized view's
  stored definition through nested view/materialized-view dependencies. If that
  provenance reaches the lifecycle outbox, reject the runtime credential regardless
  of the materialized-view owner, current copied contents, or most recent refresh
  authority; catalog shape cannot prove that a copied outbox projection remains
  tenant-local. Foreign tables are a third opaque authority boundary. PostgreSQL
  foreign-data wrappers resolve remote access through foreign servers and user
  mappings, so local RLS, local role attributes, and local relation ownership cannot
  prove the remote principal or remote row-security semantics. If the runtime can
  select a user-schema foreign table directly, an ordinary view's effective principal
  can reach one, a callable definer owner can reach one, or a runtime-readable
  materialized view has a foreign table anywhere in its stored definition provenance,
  reject the credential before tenant binding or outbox data SQL. PostgreSQL
  inheritance and declarative partitioning also allow access through a named ordinary
  or partitioned parent while a foreign descendant performs the remote read; parent
  access does not require a separate caller `SELECT` grant on the child. Admission
  must therefore build a cycle-safe foreign-ancestor closure through
  `pg_catalog.pg_inherits` and reject a selectable parent, definer-owner-selectable
  parent, view-mediated parent, or materialized provenance node whenever that relation
  has a foreign descendant. Missing caller/child ACLs, partition bounds, parent names,
  or local parent RLS are not durable evidence of remote authorization. A materialized
  copy remains opaque after the source privilege is revoked because its stored rows no
  longer require a remote read. Do not parse or allowlist mutable FDW/user-mapping
  options, current copied contents, routine body text, tenant literals in definition
  text, or last-refresh authority as a substitute for remote authorization evidence;
  workloads that need foreign-data access must use a separate role and connection from
  the lifecycle-outbox runtime credential and every callable definer owner it can
  enter. PostgreSQL permits a role administrator to grant the administered role to a
  new principal even when the administrator's own membership is `INHERIT FALSE, SET
  FALSE`; the new principal can then use the granted role's selectable path after the
  definer returns. `SECURITY DEFINER` similarly executes with its owner's privileges,
  so a safe outer owner does not make a privileged nested definer safe. Direct runtime
  `CREATEDB` and `CREATEROLE` are database/role administration capabilities outside an
  application identity; callable `CREATEROLE` is rejected because it is executable
  within the definer boundary, while `CREATEDB` remains covered when membership
  administration can grant that authority onward for later invoker-context use.
  `REPLICATION` is separate cluster-level connection and replication-slot authority
  and must not be co-located with a tenant application identity either directly or
  through an executable definer; `MAINTAIN` is relation-wide operational authority
  permitting PostgreSQL maintenance and `LOCK TABLE`, not tenant application DML;
  `SELECT`/`INSERT` grant options, DML-bearing role administration, executable
  privileged definer authority, view-mediated RLS-bypass authority, materialized
  outbox/foreign-data copies, and reachable foreign data are authorization/data-copy
  capabilities rather than application DML; `TRUNCATE` is outside RLS; tenant-local
  `DELETE` or `UPDATE` violates the append-only durable-intent invariant; and
  `REFERENCES`/`TRIGGER` can install relation behavior outside the package DML contract.
  Inert membership alone is not a bypass. Re-prove live enabled/forced RLS, the sole
  canonical tenant policy identity/command/role scope, parser-normalized `USING`/
  `WITH CHECK` predicates and allowed catalog dependencies, the absence of any
  non-internal trigger or rewrite rule attached to the canonical outbox, the exact
  live `pg_catalog.pg_constraint` set, and the live outbox index-program boundary.
  For each canonical CHECK, runtime admission must compare parser/deparser-normalized
  semantic authority from `pg_catalog.pg_get_expr(...)`; a same-name CHECK carrying a
  different semantic predicate is constraint drift and must fail closed before tenant
  binding or outbox data SQL. Runtime constraint authority is exactly the canonical
  nondeferrable primary key on `context_outbox_uuid`, the nondeferrable
  `(tenant_scope, evidence_id)` replay UNIQUE, and the three validated, inheritable
  canonical CHECK constraints; any added FK, EXCLUDE, CHECK, PK, UNIQUE,
  deferrability/validation drift, key-column drift, or missing canonical constraint
  fails closed before tenant binding or outbox data SQL. The index boundary allows no
  expression or partial index, requires the default `pg_catalog` operator class for
  each exact key type/access method, and allows no standalone UNIQUE arbiter outside
  those canonical PK/UNIQUE constraints. Runtime admission must also re-authenticate
  every omitted-column default through `pg_catalog.pg_attrdef` joined to
  `pg_catalog.pg_attribute`, deparsing each expression with
  `pg_catalog.pg_get_expr(...)`. Exactly three defaults are allowed:
  `tenant_scope = 'standalone'::text`, `context_outbox_uuid = gen_random_uuid()`, and
  `created_at = now()`. A missing or additional default, renamed default-bearing
  column, or semantically substituted expression fails closed before tenant binding or
  outbox data SQL; a migration success record does not confer continuing default-
  expression authority. The complete effective/session-selectable role, definer,
  reachable-view, reachable-materialized-copy, and reachable-foreign-data authority
  envelopes must also pass before tenant binding or outbox data SQL. A migration
  success record is point-in-time evidence and does not authorize later same-name
  policy, ACL, membership, routine, view, materialized view, foreign relation/mapping,
  role-authority, trigger, rewrite-rule, constraint-set, default-expression, or index-
  program/uniqueness drift. The normal runtime role needs only non-grantable `SELECT`
  and `INSERT` on the outbox. Replay serialization must use transaction-scoped advisory
  locking on the validated tenant/event identity rather than `SELECT ... FOR UPDATE`,
  so serialization never requires ambient row-mutation authority. Do not authenticate
  runtime connections as a database creator, role administrator, replication identity,
  relation maintainer, DML delegator, privileged definer gateway, privileged-view/
  materialized-copy/foreign-data gateway, or other administrator and rely on `SET ROLE`
  or `SET SESSION AUTHORIZATION` as a downgrade; administrative, replication,
  maintenance, grant-capable, membership-delegating, executable-privileged,
  view-mediated-RLS-bypass, materialized-copy, foreign-data, and owner-capable login
  sessions are outside the application isolation guarantee.
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