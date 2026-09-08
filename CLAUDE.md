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
  incorrect identity mapping remain outside the RLS guarantee. Caller-visible
  non-system-schema `SECURITY INVOKER` routines are part of the same executable
  boundary: when a selectable principal has schema `USAGE` and routine `EXECUTE`,
  inspect that invoker routine's `proconfig` directly and reject any function-local
  `pg_llm_batch.tenant_scope` setting before tenant binding or outbox data I/O.
  Keep the direct selectable-principal scan separate from `SECURITY DEFINER`
  owner traversal because an invoker routine retains the current execution
  principal while a definer routine changes it to the routine owner. Once a
  callable definer has changed execution to a discovered owner, that owner is
  therefore the current principal for any non-system-schema `SECURITY INVOKER`
  routine it can execute. Admission must scan such invokers through the owner's
  schema `USAGE` plus routine `EXECUTE` and reject a tenant-scope `proconfig`
  override before accepting that definer path. This still follows PostgreSQL's
  invoker principal; it does not substitute the invoker routine's owner.
- Keep row-level security enabled and forced. Runtime admission must reject
  `SUPERUSER`/`CREATEDB`/`CREATEROLE`/`REPLICATION`/`BYPASSRLS`,
  owner/destructive/programming/maintenance authority reachable from
  `CURRENT_USER`, `SESSION_USER`, or the session-selectable/administerable role
  closure, plus table- or column-level `SELECT WITH GRANT OPTION` and
  `INSERT WITH GRANT OPTION`. Outbox `MAINTAIN` is also forbidden: PostgreSQL
  defines it as relation-wide authority for maintenance operations including
  `LOCK TABLE`, not application `SELECT`/`INSERT` DML. A pure `SET TRUE` path
  does not mint membership: the intended non-grantable outbox `SELECT`/`INSERT`
  of an ordinary SET-selectable forced-RLS application role remains valid. The
  delegated-DML envelope starts only once an `ADMIN OPTION` edge has been crossed
  and that ADMIN-bearing state must then propagate recursively through later
  `SET` or `ADMIN` edges. A session identity with membership `ADMIN OPTION` over
  a role that directly/inheritedly carries outbox `SELECT`/`INSERT`/`MAINTAIN`,
  or that can reach such authority through later `SET`/`ADMIN` membership edges,
  is rejected. Callable non-system-schema `SECURITY DEFINER` routines are
  rejected when their owner can directly reintroduce forbidden authority through
  superuser, `CREATEROLE`, `REPLICATION`, RLS-bypass status, exact or inherited
  table ownership, grant options, `MAINTAIN`, `TRUNCATE`, `DELETE`, `UPDATE`,
  `REFERENCES`, or `TRIGGER`; they are also rejected when the owner can use
  membership `ADMIN OPTION` to redistribute a role that directly, or through a
  recursively mixed `SET`/`ADMIN` path, carries the forbidden runtime/operator
  envelope including `CREATEDB` or `MAINTAIN`. Do not bound that delegated-definer
  proof to one administered role plus one all-SET layer. That executable-principal
  check is transitive: once a caller can enter a user-schema `SECURITY DEFINER`,
  admission must recursively follow any further user-schema `SECURITY DEFINER`
  that the discovered owner can execute through schema `USAGE` plus routine
  `EXECUTE`, using a cycle-safe owner closure. Every callable routine in that
  closure must also pin routine-level `search_path = pg_catalog, pg_temp`; absent
  or different name-resolution authority is rejected before tenant binding or
  outbox data SQL rather than inheriting caller temporary-schema state. The
  discovered definer owner must also pass the same reachable ordinary-view,
  materialized-copy, inheritance/partition, and opaque foreign-data authority probe
  as a runtime principal. A caller's missing direct foreign-table `SELECT` is not
  safety evidence once the callable routine executes with an owner whose foreign
  server/user mapping can reach that relation; do not allowlist that authority by
  parsing one current routine body. A safe outer owner therefore cannot hide a
  dangerous inner definer that the caller cannot execute directly. Ordinary views
  form a second transitive authority boundary. Starting with each caller-selectable
  view, admission must follow the cycle-safe nested-view dependency closure using the
  principal PostgreSQL actually applies at each edge: the original invoker for
  `security_invoker=true`, otherwise the current view owner. Any reachable
  non-security-invoker view that directly reads the outbox is rejected when its owner
  is a superuser or `BYPASSRLS` principal with outbox read authority. This prevents a
  safe-looking outer view from hiding a privileged inner view that exposes
  cross-tenant rows to a `NOBYPASSRLS` runtime credential. Materialized views are a
  separate copied-data boundary. PostgreSQL returns their persisted rows directly at
  read time and uses the stored defining query only when the relation is populated or
  refreshed, so a runtime base-table RLS check does not protect an older materialized
  copy. Admission must include materialized relations that are directly
  caller-selectable or reached through an ordinary view, then follow each materialized
  relation's definition provenance through nested ordinary/materialized views. If that
  provenance reaches the lifecycle outbox, reject the credential before tenant binding
  or outbox SQL; do not infer safety from the materialized-view owner, mutable copied
  contents, a tenant literal in definition text, or the authority used by the last
  refresh. Foreign tables are another opaque authority boundary: a foreign-data wrapper
  uses a foreign server and user mapping to determine remote access, so local RLS and
  role catalogs cannot prove the remote principal or remote row-security semantics.
  Reject any user-schema foreign table selectable by the runtime, reachable through an
  ordinary view under that view's effective principal, reachable by a callable definer
  owner, or present anywhere in the stored definition provenance of a runtime-readable
  materialized view before tenant binding or outbox SQL. PostgreSQL inheritance and
  declarative partitioning can also route a parent-table query into a foreign descendant
  while access permission is checked on the named parent. Admission must build a
  cycle-safe foreign-ancestor closure through `pg_catalog.pg_inherits` and reject any
  selectable ordinary or partitioned parent, definer-owner-selectable parent,
  view-mediated parent, or materialized provenance node with a foreign descendant.
  Missing caller/child `SELECT`, partition bounds, parent names, and local parent RLS
  are not durable remote-authorization evidence. A materialized foreign-data copy
  remains opaque even after caller access to the source foreign table is revoked
  because the copied rows no longer require another remote read. Do not treat mutable
  FDW/user-mapping options, copied contents, routine body text, tenant literals in
  definition text, or last-refresh authority as durable authorization evidence;
  foreign-data workloads must use a role/connection separate from the lifecycle-
  outbox runtime credential and every callable definer owner it can enter.
  PostgreSQL lets the membership administrator grant a role onward even when that
  administrator's own membership is `INHERIT FALSE, SET FALSE`; the recipient can
  then use the granted selectable path after a security-definer call returns.
  `SECURITY DEFINER` executes with its owner's privileges rather than the caller's
  privileges. Admission must re-prove the sole canonical tenant policy's command,
  role scope, permissive mode, `USING`/`WITH CHECK` predicates, reviewed catalog
  dependencies, the absence of any non-internal trigger or rewrite rule attached to
  the canonical outbox, the exact live `pg_catalog.pg_constraint` set, and the live
  outbox index-program boundary. For each canonical CHECK, runtime admission must
  compare parser/deparser-normalized semantic authority from
  `pg_catalog.pg_get_expr(...)`; a same-name CHECK carrying a different semantic
  predicate is constraint drift and must fail closed before tenant binding or outbox
  SQL. CHECK dependency identity is part of that authority: deparse equality is
  necessary but not sufficient. Runtime admission must inspect
  `pg_catalog.pg_depend` and reject any whole-object normal dependency of an admitted
  CHECK before tenant binding or outbox data SQL. A user-schema operator or function
  selected by caller `search_path` can be same-deparse while referring to a different
  object OID, so its displayed token is not canonical identity. Runtime constraint
  authority is exactly the canonical nondeferrable primary key on
  `context_outbox_uuid`, the nondeferrable `(tenant_scope, evidence_id)` replay UNIQUE,
  and the three validated, inheritable canonical CHECK constraints; added
  FK/EXCLUDE/CHECK/PK/UNIQUE constraints or validation, deferrability, key-column, or
  missing-canonical-constraint drift fails closed before tenant binding or outbox SQL.
  Expression and partial indexes are rejected, every simple key must use the default
  `pg_catalog` operator class for its exact type/access method, and standalone UNIQUE
  indexes are rejected unless they back the canonical primary key or replay
  constraint. Runtime admission must also re-authenticate every omitted-column default
  from `pg_catalog.pg_attrdef` joined to `pg_catalog.pg_attribute` and deparse each
  expression through `pg_catalog.pg_get_expr(...)`. Deparse equality is necessary but
  not sufficient default authority: admission must also authenticate each admitted
  default's dependency identity through `pg_catalog.pg_depend` and reject any normal
  dependency attached to that default before tenant binding or outbox data SQL.
  Exactly three defaults are permitted: `tenant_scope = 'standalone'::text`,
  `context_outbox_uuid = gen_random_uuid()`, and `created_at = now()`. Any missing or
  additional default, renamed default-bearing column, or semantically substituted
  expression fails closed before tenant binding or outbox data SQL; migration success
  does not confer continuing default-expression authority. The full reachable
  privileged-view/materialized-copy/foreign-data boundary must also pass before tenant
  binding or outbox SQL. Direct runtime `CREATEDB` and `CREATEROLE` are database/role
  administration capabilities; callable `CREATEROLE` is executable within the definer
  boundary, while `CREATEDB` remains covered when membership administration grants that
  authority onward for later invoker-context use. `REPLICATION` is separate
  cluster-level connection and slot authority whether held directly or anywhere in the
  callable-definer owner closure, and direct DML grant options, relation maintenance,
  authority-bearing role administration, executable privileged definer authority,
  view-mediated RLS bypass authority, materialized outbox/foreign-data copies, and
  reachable foreign data are outside application DML. Runtime identities remain
  `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` and need only
  non-grantable outbox `SELECT` and `INSERT`. Migration success is point-in-time
  evidence, not continuing authority after policy, ACL, membership, routine, view,
  materialized view, foreign relation/mapping, role-attribute, trigger, rewrite-rule,
  constraint-set, default-expression, or index-program/uniqueness DDL.
- The outbox write path must close the admission-to-write DDL race. Before live
  authority admission, `enqueue_in_transaction()` acquires `LOCK TABLE ONLY
  public.llm_context_lifecycle_outbox IN ROW EXCLUSIVE MODE` and retains that table
  lock through the durable `INSERT` and caller-owned transaction. This is the normal
  table lock class used by PostgreSQL modifying DML, pulled forward so a concurrent
  `CREATE TRIGGER` or other conflicting schema DDL cannot change executable write
  authority between the catalog proof and the statement that consumes it. Do not
  replace this with an advisory lock, a post-hoc recheck, or `ACCESS EXCLUSIVE`.
  Ordinary application roles remain limited to non-grantable `SELECT`/`INSERT`; the
  existing `INSERT` privilege is sufficient to acquire `ROW EXCLUSIVE`. Treat lock
  acquisition and contention as part of complete buyer-path latency evidence.
- The outbox read path must close the corresponding admission-to-read relation-identity
  race. Before live authority admission, `load_in_transaction()` acquires `LOCK TABLE
  ONLY public.llm_context_lifecycle_outbox IN ACCESS SHARE MODE` and retains it through
  tenant binding, optional tenant/event advisory serialization, and the consuming
  `SELECT`. Do not rely on the later `SELECT` to acquire its ordinary `ACCESS SHARE`
  lock after admission: concurrent `ACCESS EXCLUSIVE` DDL could rename or replace the
  admitted relation in that gap. Do not widen reads to `ROW EXCLUSIVE` or
  `ACCESS EXCLUSIVE`; `ACCESS SHARE` is the minimal relation-identity fence and remains
  compatible with ordinary reads and writes. Its acquisition/wait is part of complete
  buyer-path latency evidence rather than removable security overhead.
- Keep owner-enforcement relaxation, legacy backfill, constraint migration, and
  forced-RLS restoration inside one atomic PostgreSQL statement.
- Keep `pg_llm_batch/schema.sql` and
  `docker/postgres/init/02_schema.sql` byte-for-byte identical.
- Keep README, operator, architecture, ADR, doctoring, and CHANGELOG contracts
  synchronized with every tenant security or migration change.
- Maintain 100% production statement, branch, and public-docstring coverage.
  Add realistic migration, rollback, compatibility, security, and
  tenant-isolation tests before implementation changes.