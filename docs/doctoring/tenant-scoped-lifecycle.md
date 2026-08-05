# Tenant-Scoped Durable Lifecycle Isolation

## Decision and trust boundary

Shared-table deployments use a trusted local `tenant_scope` as part of the durable lifecycle identity. The embedding host selects this value only after authentication and authorization. Provider metadata, remote identifiers, endpoint aliases, request payloads, and transport headers are not tenant authorities.

`TenantDurableBatchAPIClient` validates the scope without trimming or coercion before reservation, credential resolution, provider I/O, or database I/O. Existing `DurableBatchAPIClient` consumers retain the original recorder seam under the explicit `standalone` scope.

## Database enforcement

The durable identity is `(tenant_scope, endpoint_alias, remote_batch_id)`. Every package lifecycle statement binds the validated scope using parameterized, transaction-local `set_config('pg_llm_batch.tenant_scope', ..., true)` before table access.

PostgreSQL row-level security uses matching `USING` and `WITH CHECK` expressions. RLS is enabled and forced. Missing context therefore has no matching row policy. PostgreSQL superusers and roles carrying `BYPASSRLS` bypass this mechanism and cannot be used as production application identities.

## Migration and rollback

Existing rows are backfilled to `standalone`; no lifecycle row is deleted or merged. The former endpoint/provider unique constraint is replaced by a tenant-qualified constraint. The temporary owner-enforcement transition, legacy backfill, constraint migration, and `FORCE ROW LEVEL SECURITY` restoration execute inside one anonymous PostgreSQL block. This prevents psql autocommit from committing an intermediate owner-bypass state.

Rollback to the former two-column key is unsafe until an operator proves that no `(endpoint_alias, remote_batch_id)` pair appears in more than one tenant scope. The packaged schema and Docker initialization schema remain byte-for-byte identical and must support idempotent reapplication.

## Verification

Deterministic tests cover strict scope syntax, pre-effect validation, tenant-recorder propagation, standalone compatibility, parameterized transaction context, tenant-qualified conflict targets and reads, malformed database rows, migration preservation, atomic RLS restoration, policy default-deny behavior, and exact schema mirroring. Production statement, branch, and public-docstring coverage remain at 100%.

Live PostgreSQL verification uses a `NOSUPERUSER NOBYPASSRLS` role, persists the same provider identifier in two tenant scopes, and confirms each scope can retrieve only its own lifecycle projection. Migration tests reapply the schema to detect non-idempotent DDL and rollback hazards.

## References

Joint Task Force. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53, Revision 5). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

OWASP Foundation. (n.d.). *Multi-tenant security cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html

PostgreSQL Global Development Group. (2026a). *Row security policies*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026b). *System administration functions*. In *PostgreSQL 18 documentation*. https://www.postgresql.org/docs/18/functions-admin.html
