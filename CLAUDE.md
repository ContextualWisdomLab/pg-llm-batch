# CLAUDE.md

## Tenant lifecycle invariants

- Preserve the standalone client, its four-argument recorder seam, and the
  explicit `standalone` database scope.
- Never derive tenant scope from provider metadata, remote identifiers, request
  bodies, model output, endpoint aliases, or transport headers.
- Validate tenant scope before observation reservation, credential lookup,
  provider I/O, or database I/O.
- Bind validated scope as a parameter with transaction-local `set_config`
  before lifecycle table access.
- Include tenant scope in every lifecycle lookup, unique identity, conflict
  target, and operational status index.
- Treat the custom setting as a trusted application boundary rather than a
  credential. A database role with arbitrary SQL can call `set_config` for an
  arbitrary tenant scope, so generic tenant-controlled SQL, SQL injection, and
  incorrect identity mapping remain outside the RLS guarantee.
- Keep row-level security enabled and forced. Runtime admission must reject
  `SUPERUSER`/`CREATEDB`/`CREATEROLE`/`REPLICATION`/`BYPASSRLS`,
  owner/destructive/programming/maintenance authority reachable from
  `CURRENT_USER`, `SESSION_USER`, or the session-selectable/administerable role
  closure, plus table- or column-level `SELECT WITH GRANT OPTION` and
  `INSERT WITH GRANT OPTION`. Outbox `MAINTAIN` is also forbidden: PostgreSQL
  defines it as relation-wide authority for maintenance operations including
  `LOCK TABLE`, not application `SELECT`/`INSERT` DML. A session identity with
  membership `ADMIN OPTION` over a role that directly/inheritedly carries outbox
  `SELECT`/`INSERT`/`MAINTAIN`, or that can reach such authority through an
  all-`SET TRUE` membership path, is also rejected. Callable non-system-schema
  `SECURITY DEFINER` routines are rejected when their owner can directly
  reintroduce forbidden authority through superuser, `CREATEROLE`, `REPLICATION`,
  RLS-bypass status, exact or inherited table ownership, grant options,
  `MAINTAIN`, `TRUNCATE`, `DELETE`, `UPDATE`, `REFERENCES`, or `TRIGGER`; they are
  also rejected when the owner can use membership `ADMIN OPTION` to redistribute
  a role that directly, or through an all-`SET TRUE` path, carries the forbidden
  runtime/operator envelope including `CREATEDB` or `MAINTAIN`. That executable-
  principal check is transitive: once a caller can enter a user-schema
  `SECURITY DEFINER`, admission must recursively follow any further user-schema
  `SECURITY DEFINER` that the discovered owner can execute through schema `USAGE`
  plus routine `EXECUTE`, using a cycle-safe owner closure. Every callable routine
  in that closure must also pin routine-level `search_path = pg_catalog, pg_temp`;
  absent or different name-resolution authority is rejected before tenant binding
  or outbox data SQL rather than inheriting caller temporary-schema state. A safe
  outer owner therefore cannot hide a dangerous inner definer that the caller
  cannot execute directly. Ordinary views form a second transitive authority
  boundary. Starting with each caller-selectable view, admission must follow the
  cycle-safe nested-view dependency closure using the principal PostgreSQL actually
  applies at each edge: the original invoker for `security_invoker=true`, otherwise
  the current view owner. Any reachable non-security-invoker view that directly
  reads the outbox is rejected when its owner is a superuser or `BYPASSRLS`
  principal with outbox read authority. This prevents a safe-looking outer view from
  hiding a privileged inner view that exposes cross-tenant rows to a
  `NOBYPASSRLS` runtime credential. Materialized views are a separate copied-data
  boundary. PostgreSQL returns their persisted rows directly at read time and uses
  the stored defining query only when the relation is populated or refreshed, so a
  runtime base-table RLS check does not protect an older materialized copy. Admission
  must include materialized relations that are directly caller-selectable or reached
  through an ordinary view, then follow each materialized relation's definition
  provenance through nested ordinary/materialized views. If that provenance reaches
  the lifecycle outbox, reject the credential before tenant binding or outbox SQL;
  do not infer safety from the materialized-view owner, mutable copied contents, a
  tenant literal in definition text, or the authority used by the last refresh.
  Foreign tables are another opaque authority boundary: a foreign-data wrapper uses
  a foreign server and user mapping to determine remote access, so local RLS and role
  catalogs cannot prove the remote principal or remote row-security semantics. Reject
  any user-schema foreign table selectable by the runtime, or reachable through an
  ordinary view under that view's effective principal, before tenant binding or
  outbox SQL. Do not treat mutable FDW/user-mapping options as durable authorization
  evidence; foreign-data workloads must use a role/connection separate from the
  lifecycle-outbox runtime credential.
  PostgreSQL lets the membership administrator grant a role onward even when that
  administrator's own membership is `INHERIT FALSE, SET FALSE`; the recipient can
  then use the granted selectable path after a security-definer call returns.
  `SECURITY DEFINER` executes with its owner's privileges rather than the caller's
  privileges. Admission must re-prove the sole canonical tenant policy's command,
  role scope, permissive mode, `USING`/`WITH CHECK` predicates, reviewed catalog
  dependencies, and the full reachable privileged-view/materialized-copy/foreign-
  table boundary before tenant binding or outbox SQL. Direct runtime `CREATEDB` and
  `CREATEROLE` are database/role administration capabilities; callable `CREATEROLE`
  is executable within the definer boundary, while `CREATEDB` remains covered when
  membership administration grants that authority onward for later invoker-context
  use. `REPLICATION` is separate cluster-level connection and slot authority whether
  held directly or anywhere in the callable-definer owner closure, and direct DML
  grant options, relation maintenance, authority-bearing role administration,
  executable privileged definer authority, view-mediated RLS bypass authority,
  materialized outbox copies, and reachable foreign data are outside application
  DML. Runtime identities remain `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  NOBYPASSRLS` and need only non-grantable outbox `SELECT` and `INSERT`. Migration
  success is point-in-time evidence, not continuing authority after policy, ACL,
  membership, routine, view, materialized view, foreign relation/mapping, or role-
  attribute DDL.
- Keep owner-enforcement relaxation, legacy backfill, constraint migration, and
  forced-RLS restoration inside one atomic PostgreSQL statement.
- Keep `pg_llm_batch/schema.sql` and
  `docker/postgres/init/02_schema.sql` byte-for-byte identical.
- Keep README, operator, architecture, ADR, doctoring, and CHANGELOG contracts
  synchronized with every tenant security or migration change.
- Maintain 100% production statement, branch, and public-docstring coverage.
  Add realistic migration, rollback, compatibility, security, and
  tenant-isolation tests before implementation changes.
