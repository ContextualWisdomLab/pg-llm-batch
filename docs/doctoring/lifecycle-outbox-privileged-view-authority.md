# Lifecycle outbox privileged-view authority

## Finding

The lifecycle outbox runtime admission already rejects direct `BYPASSRLS`/superuser identities and callable privileged `SECURITY DEFINER` routines, but that is not sufficient when the same runtime credential can `SELECT` a PostgreSQL view whose execution path eventually reaches the outbox under a privileged view owner. PostgreSQL 18 applies permissions and row-level-security policies for underlying relations using a view owner's rights by default. A view marked `security_invoker=true` instead uses the invoking principal's permissions and policies. This distinction creates an indirect tenant-boundary authority path even when the authenticated runtime login itself is `NOBYPASSRLS`.

The executable specimen added at RED commit `da5b109be87c126eb618922c274bb858b57d7b71` creates two lifecycle rows for different tenants, proves the ordinary runtime caller sees one row through the forced-RLS base table, and proves the same caller sees both rows through a directly outbox-dependent, caller-selectable view owned by a separate `BYPASSRLS` role. The package call on the pre-repair authority model would therefore have admitted a credential that retained a usable cross-tenant read capability outside the package-authored SQL path.

A second fresh review found the direct-view repair incomplete. RED commit `5e38538395e28b1c02bcb15129225576d8e1e414` adds an outer view owned by an ordinary `NOBYPASSRLS` role. The runtime caller can select only that outer view. Its owner can select a hidden inner view owned by the `BYPASSRLS` principal, and the inner view directly reads the outbox. The runtime caller has no direct `SELECT` on the inner view, yet selecting the outer view still returns both tenants. A direct caller-to-leaf predicate therefore misses a real nested view authority path.

## Decision

Production repair `31f037ea0f4781f2c39020e78248a0c94c7eb969` keeps runtime admission in the existing single catalog round trip and extends the selectable-role authority envelope with a cycle-safe catalog proof over `pg_class`, `pg_namespace`, `pg_rewrite`, and `pg_depend`.

For each role in the effective/session-selectable/administerable closure, admission seeds a `reachable_view(view_oid, caller_oid)` relation with each non-system ordinary view for which that role has schema `USAGE` and view `SELECT`. It then follows view-to-view rewrite dependencies recursively. The principal that must be able to select the next view is the original caller for a `security_invoker=true` current view and otherwise the current view owner, matching PostgreSQL's invoker/owner execution distinction. `UNION` rather than `UNION ALL` makes the finite catalog closure cycle-safe.

Admission rejects the credential when any reachable ordinary view directly depends on `public.llm_context_lifecycle_outbox`, is not `security_invoker=true`, and is owned by a `SUPERUSER` or `BYPASSRLS` principal with outbox read authority. The repair does not parse mutable view SQL text, mutate ownership or ACLs, drop views, weaken forced RLS, or add another database round trip. The direct and nested positive controls set the leaf view to `security_invoker=true`; PostgreSQL then applies the invoking principal's tenant RLS and both paths return only the admitted tenant.

Materialized-view residual data is intentionally not represented as an ordinary-view RLS execution path. A materialized view stores a snapshot and therefore requires a separate ownership/data-copy review; it must not be inferred as covered by this `relkind = 'v'` authority closure until its own realistic evidence and lifecycle policy are established.

## Security effect

A runtime DSN is treated as an authority-bearing credential, not merely as a path used by package-authored SQL. If that credential can traverse one or more views and eventually cause PostgreSQL to evaluate the outbox under a `BYPASSRLS` or superuser owner, the credential is outside the supported tenant-scoped append-only boundary even when every package-authored query remains tenant-qualified. The guard therefore fails before `pg_llm_batch.tenant_scope` is bound or durable outbox rows are read or written.

## Verification boundary

The final claim requires exact-head hosted PostgreSQL/container execution of both the direct and nested specimens plus the existing Python 3.10/3.12/3.14, 100% owned-production statement/branch coverage, 100% public-docstring, lint/package, and Release Acceptance gates. A queued or predecessor run is not GREEN evidence.

## References

PostgreSQL Global Development Group. (2026). *CREATE POLICY*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026). *CREATE VIEW*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createview.html

PostgreSQL Global Development Group. (2026). *Rules and privileges*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/rules-privileges.html

PostgreSQL Global Development Group. (2026). *CREATE ROLE*. PostgreSQL 18 documentation. https://www.postgresql.org/docs/18/sql-createrole.html
