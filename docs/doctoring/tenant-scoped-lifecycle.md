# Tenant-Scoped Durable Lifecycle Isolation

## Decision and trust boundary

Shared-table deployments use a trusted local `tenant_scope` as part of the
durable lifecycle identity. The embedding host selects this value only after
authentication and authorization. Provider metadata, remote identifiers,
endpoint aliases, request payloads, model output, and transport headers are not
tenant authorities.

`TenantDurableBatchAPIClient` validates the scope without trimming or coercion
before reservation, credential resolution, provider I/O, or database I/O.
Existing `DurableBatchAPIClient` consumers retain the original recorder seam
under the explicit `standalone` scope.

## Database enforcement

The durable identity is `(tenant_scope, endpoint_alias, remote_batch_id)`.
Every package lifecycle statement binds the validated scope using parameterized,
transaction-local `set_config('pg_llm_batch.tenant_scope', ..., true)` before
table access.

PostgreSQL row-level security uses matching `USING` and `WITH CHECK`
expressions. RLS is enabled and forced. Missing context therefore has no matching
row policy. PostgreSQL superusers and roles carrying `BYPASSRLS` bypass this
mechanism and cannot be used as production application identities.

Lifecycle-outbox migration policy predicates bind text equality with
`OPERATOR(pg_catalog.=)` and resolve the tenant setting through
`pg_catalog.current_setting`. PostgreSQL records the applicable command,
permissive/restrictive mode, roles, `USING`, and `WITH CHECK` expression trees
separately in `pg_policy`; the policy name is not sufficient security evidence.
Migration 0008 therefore accepts canonical v2 without DDL only when the stored
catalog row is all-command, permissive, exactly `PUBLIC`, and both expressions
decompile to the expected tenant equality. Same-name semantic drift is repaired.
An unknown policy name fails closed rather than being silently kept or deleted,
because an additional permissive policy could widen visible/writeable rows. The
resulting canonical v2 is verified again through `pg_policy` and `pg_get_expr`
before v1/legacy policy retirement. A semantically current v2 remains unchanged
on idempotent reapplication (PostgreSQL Global Development Group, 2026e, 2026f,
2026h).

The lifecycle outbox also removes ambient PostgreSQL `search_path` from object
authority, but the runtime seam does so without changing caller transaction
state. Runtime tenant binding calls fully qualified `pg_catalog.set_config` and
runtime reads/writes address `public.llm_context_lifecycle_outbox` explicitly.
The earlier candidate that executed `SET LOCAL search_path` was superseded after
review showed that the changed path would remain active for unrelated SQL in the
caller-owned transaction.

Forward migration and rollback are installer-owned atomic statements, so their
`DO` blocks execute fully qualified
`pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true)`
before object resolution. PostgreSQL normally searches temporary schemas
specially when they are not explicitly named; putting `pg_temp` last prevents a
same-named temporary relation from preceding the reviewed application schema in
those statements (PostgreSQL Global Development Group, 2026g). This control
assumes `public` is the trusted package application schema; an operator must not
grant untrusted principals `CREATE` there.

`PostgresContextLifecycleOutboxStore` requires an explicit PostgreSQL DSN but
does not expose that exact value as a public store property. A DSN can contain
database credentials; the admitted value therefore remains package-internal
connection authority in the weak binding used by `load()` and `enqueue()`.
Tenant scope and its content-free digest stay observable because they are the
local authorization/evidence identities. This is an accidental-disclosure
control for normal logging and diagnostics, not an attempt to defend secrets
from arbitrary code executing inside the same Python process (Joint Task Force,
2020).

The setting itself is not a credential. PostgreSQL accepts custom two-part
configuration names, so a role that can execute arbitrary SQL can call
`set_config` with an arbitrary tenant scope. This design is a **trusted
application boundary** and is not a substitute for authentication,
authorization, SQL-injection prevention, restricted database privileges, or an
identity-to-tenant mapping layer. Generic SQL consoles and raw tenant-controlled
SQL must not use the application lifecycle role. Deployments that require direct
SQL should add a separately reviewed role mapping or security-definer interface.

## Migration and rollback

Existing rows are backfilled to `standalone`; no lifecycle row is deleted or
merged. The former endpoint/provider unique constraint is replaced by a
tenant-qualified constraint. The temporary owner-enforcement transition,
legacy-row backfill, constraint migration, `ENABLE ROW LEVEL SECURITY`, and
`FORCE ROW LEVEL SECURITY` restoration execute inside one anonymous PostgreSQL
block. A legacy installation therefore cannot commit a migrated table while RLS
is still disabled; policy recreation afterward remains default-deny until the
new policy exists.

Rollback to the former two-column key is unsafe until an operator proves that no
`(endpoint_alias, remote_batch_id)` pair appears in more than one tenant scope.
The lifecycle-outbox rollback additionally binds the reviewed search path before
`to_regclass`, emptiness inspection, and `DROP TABLE`, so ambient or temporary
same-name relations cannot redirect the destructive decision. The packaged
schema and Docker initialization schema remain byte-for-byte identical and must
support idempotent reapplication.

Enabling RLS is an operational compatibility change for direct SQL consumers.
Queries that do not bind an authorized transaction-local scope become
default-deny. Such consumers must migrate to the package helpers or a reviewed
database interface before deployment. Caller-owned outbox methods require a
real transaction for the transaction-local tenant GUC, but preserve the
caller's existing `search_path` rather than imposing one.

## Verification

Deterministic tests cover strict scope syntax, pre-effect validation,
tenant-recorder propagation, standalone compatibility, parameterized
transaction context, tenant-qualified conflict targets and reads, malformed
database rows, migration preservation, atomic RLS restoration, policy
default-deny behavior, exact schema mirroring, versioned policy convergence,
explicit `pg_catalog` operator/function binding, full canonical `pg_policy`
command/role/expression identity, unknown-policy fail-closed behavior,
post-create/post-repair catalog verification, runtime schema qualification
without caller `search_path` mutation, installer/rollback search-path binding,
non-exposure of an admitted credential-bearing outbox DSN, and documentation of
the bounded assurance claim. Production statement, branch, and public-docstring
coverage remain at 100% only when exact-head CI proves those gates.

Live PostgreSQL verification uses a `NOSUPERUSER NOBYPASSRLS` role, persists the
same provider identifier in two tenant scopes, and confirms each package-bound
scope can retrieve only its own lifecycle projection. This proves RLS mechanics
under the trusted package model; it does not claim protection after arbitrary
SQL execution is granted. Exact-head runtime verification must also exercise a
non-default caller `search_path`, confirm the canonical outbox relation is still
selected, confirm the caller's path is unchanged afterward, and execute
migration 0008 so PostgreSQL evaluates the final `pg_policy` postcondition.

## References

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Revision 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

MITRE. (2026). *CWE-89: Improper neutralization of special elements used in an
SQL command ('SQL injection')* (Version 4.20).
https://cwe.mitre.org/data/definitions/89.html

OWASP Foundation. (n.d.). *Multi-tenant security cheat sheet*. OWASP Cheat
Sheet Series. Retrieved August 5, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html

PostgreSQL Global Development Group. (2026a). *Customized options*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/runtime-config-custom.html

PostgreSQL Global Development Group. (2026b). *Row security policies*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026c). *SET*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/sql-set.html

PostgreSQL Global Development Group. (2026d). *System administration
functions*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-admin.html

PostgreSQL Global Development Group. (2026e). *pg_policy*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/catalog-pg-policy.html

PostgreSQL Global Development Group. (2026f). *CREATE POLICY*. In *PostgreSQL
18 documentation*. https://www.postgresql.org/docs/18/sql-createpolicy.html

PostgreSQL Global Development Group. (2026g). *Schemas*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/18/ddl-schemas.html

PostgreSQL Global Development Group. (2026h). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html
