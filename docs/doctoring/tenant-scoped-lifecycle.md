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
The packaged schema and Docker initialization schema remain byte-for-byte
identical and must support idempotent reapplication.

Enabling RLS is an operational compatibility change for direct SQL consumers.
Queries that do not bind an authorized transaction-local scope become
default-deny. Such consumers must migrate to the package helpers or a reviewed
database interface before deployment.

## Verification

Deterministic tests cover strict scope syntax, pre-effect validation,
tenant-recorder propagation, standalone compatibility, parameterized
transaction context, tenant-qualified conflict targets and reads, malformed
database rows, migration preservation, atomic RLS restoration, policy
default-deny behavior, exact schema mirroring, and documentation of the bounded
assurance claim. Production statement, branch, and public-docstring coverage
remain at 100%.

Live PostgreSQL verification uses a `NOSUPERUSER NOBYPASSRLS` role, persists the
same provider identifier in two tenant scopes, and confirms each package-bound
scope can retrieve only its own lifecycle projection. This proves RLS mechanics
under the trusted package model; it does not claim protection after arbitrary
SQL execution is granted.

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
