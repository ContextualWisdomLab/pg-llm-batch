# ADR 0002: Tenant-Scoped Durable Lifecycle State

- Status: Accepted
- Date: 2026-08-05

## Context

Provider batch identifiers are not globally unique across customer tenants. A
lifecycle table keyed only by endpoint alias and provider identifier cannot
provide a defensible shared-table identity. Provider metadata is untrusted data
and cannot establish tenant authority.

The package also needs to remain independently operable for existing
single-tenant consumers while providing a consistent integration boundary for
CWL services such as `naruon` and `contextual-orchestrator`.

## Decision

Shared-table deployments must provide a trusted local `tenant_scope` selected
after host authentication and authorization. The lifecycle business key is
`(tenant_scope, endpoint_alias, remote_batch_id)`. Package reads and writes bind
the validated scope transaction-locally, and PostgreSQL row-level security is
enabled and forced.

The custom PostgreSQL setting is not a credential. This decision assumes a
trusted application boundary that prevents untrusted arbitrary SQL and maps an
authorized identity to the tenant scope. A role able to execute arbitrary SQL
can call `set_config` with an arbitrary tenant scope; therefore RLS is not a
substitute for authentication, authorization, SQL-injection prevention, or
restricted database privileges.

The existing `DurableBatchAPIClient` remains source compatible under the
explicit `standalone` scope. Shared deployments use
`TenantDurableBatchAPIClient` and its tenant-qualified recorder seam. Direct SQL
consumers must migrate to package helpers or a separately reviewed
identity-binding database interface.

Legacy rows are backfilled to `standalone`. Owner enforcement may be relaxed
only inside the same atomic SQL statement that performs the backfill, enables
row-level security for legacy tables, and restores `FORCE ROW LEVEL SECURITY`.
Policy recreation follows under enabled and forced default-deny behavior.

## Consequences

Embedding hosts must derive tenant scope from a trusted identity boundary and
use application roles that are `NOSUPERUSER NOBYPASSRLS`. Provider, model, and
transport values cannot select scope. Generic tenant-controlled SQL must not use
the lifecycle application role.

The tenant-qualified key allows identical provider identifiers in separate
tenants without collision. A missing transaction-local scope is default-deny,
which intentionally changes direct SQL behavior for existing integrations.

Rollback to the prior two-column key requires first proving that no
endpoint/provider pair exists in multiple tenants and supplying a replacement
authorization boundary. Packaged and deployable schemas must remain exact
mirrors, and schema reapplication must be idempotent.
