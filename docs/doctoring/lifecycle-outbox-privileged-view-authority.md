# Lifecycle outbox privileged-view authority

## Finding

The lifecycle outbox runtime admission already rejects direct `BYPASSRLS`/superuser identities and caller-visible privileged `SECURITY DEFINER` routines, but that is not sufficient when the same runtime credential can `SELECT` a normal PostgreSQL view whose owner bypasses RLS. PostgreSQL 18 applies permissions and row-level-security policies for underlying relations using the view owner's rights by default. A view marked `security_invoker=true` instead uses the invoking user's permissions and policies. This distinction creates an indirect tenant-boundary authority path even when the runtime login itself is `NOBYPASSRLS`.

The executable specimen added at RED commit `da5b109be87c126eb618922c274bb858b57d7b71` creates two lifecycle rows for different tenants, proves the ordinary runtime caller sees one row through the forced-RLS base table, and proves the same caller sees both rows through a directly outbox-dependent, caller-selectable view owned by a separate `BYPASSRLS` role. The package call on the pre-repair authority model would therefore have admitted a credential that retained a usable cross-tenant read capability outside the package SQL path.

## Decision

Production repair `d6d65a8f69be651bacb5b24a704bf22ae207b0ce` keeps runtime admission in the existing single catalog round trip and extends the selectable-role authority envelope with a catalog proof over `pg_class`, `pg_namespace`, `pg_rewrite`, and `pg_depend`. For each role in the effective/session-selectable/administerable closure, admission rejects a caller-selectable, non-system ordinary view when all of the following hold:

- the view directly depends on `public.llm_context_lifecycle_outbox`;
- the runtime-selectable role has schema `USAGE` and view `SELECT`;
- the view is not `security_invoker=true`;
- the view owner can read at least one outbox column; and
- the view owner is `SUPERUSER` or `BYPASSRLS`.

The repair does not parse view SQL text, mutate ownership or ACLs, drop views, weaken forced RLS, or promote a mutable sibling contract. The positive control changes only the specimen view to `security_invoker=true`; PostgreSQL then applies the runtime caller's tenant RLS and the package admits the otherwise unchanged safe credential.

This slice intentionally proves the direct outbox-dependent view path. Nested view/rule closure and materialized-view residual-data authority are separate review targets and must not be inferred as covered by this direct-dependency predicate until executable evidence exists.

## Security effect

A runtime DSN is treated as an authority-bearing credential, not merely as a path used by package-authored SQL. If that credential can reach a view that causes PostgreSQL to evaluate the outbox under a `BYPASSRLS` or superuser owner, the credential is outside the supported tenant-scoped append-only boundary even when every package query remains tenant-qualified. The guard therefore fails before `pg_llm_batch.tenant_scope` is bound or durable outbox rows are read or written.

## Verification boundary

The final claim requires exact-head hosted PostgreSQL/container execution of the specimen plus the existing Python 3.10/3.12/3.14, 100% owned-production statement/branch coverage, 100% public-docstring, lint/package, and Release Acceptance gates. A queued or predecessor run is not GREEN evidence.

## References

PostgreSQL Global Development Group. (2026). *CREATE POLICY*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026). *CREATE VIEW*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createview.html

PostgreSQL Global Development Group. (2026). *Rules and privileges*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/rules-privileges.html

PostgreSQL Global Development Group. (2026). *CREATE ROLE*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createrole.html
