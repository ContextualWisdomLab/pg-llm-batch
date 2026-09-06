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
  owner/destructive/programming authority reachable from `CURRENT_USER`,
  `SESSION_USER`, or the session-selectable/administerable role closure, plus
  table- or column-level `SELECT WITH GRANT OPTION` and
  `INSERT WITH GRANT OPTION`. A session identity with membership `ADMIN OPTION`
  over a role that directly/inheritedly carries outbox `SELECT`/`INSERT`, or
  that can reach a DML-bearing role through an all-`SET TRUE` membership path,
  is also rejected. PostgreSQL lets that administrator grant the role onward,
  after which the recipient can inherit the DML or use the same `SET ROLE` path
  even though the table ACLs themselves are non-grantable. Admission must
  re-prove the sole canonical tenant policy's command, role scope, permissive
  mode, `USING`/`WITH CHECK` predicates, and reviewed catalog dependencies before
  tenant binding or outbox SQL. `CREATEDB` and `CREATEROLE` are database/role
  administration capabilities, `REPLICATION` is separate cluster-level
  connection and slot authority, and both direct DML grant options and
  DML-bearing role administration are authorization-delegation authority; none
  belongs to application DML. Runtime identities remain
  `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` and need only
  non-grantable outbox `SELECT` and `INSERT`. Migration success is point-in-time
  evidence, not continuing authority after policy, ACL, membership, or
  role-attribute DDL.
- Keep owner-enforcement relaxation, legacy backfill, constraint migration, and
  forced-RLS restoration inside one atomic PostgreSQL statement.
- Keep `pg_llm_batch/schema.sql` and
  `docker/postgres/init/02_schema.sql` byte-for-byte identical.
- Keep README, operator, architecture, ADR, doctoring, and CHANGELOG contracts
  synchronized with every tenant security or migration change.
- Maintain 100% production statement, branch, and public-docstring coverage.
  Add realistic migration, rollback, compatibility, security, and
  tenant-isolation tests before implementation changes.