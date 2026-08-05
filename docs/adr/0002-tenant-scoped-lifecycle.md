# ADR 0002: Tenant-Scoped Durable Lifecycle State

- Status: Accepted
- Date: 2026-08-05

## Context

Provider batch identifiers are not globally unique across customer tenants. A lifecycle table keyed only by endpoint alias and provider identifier cannot provide a defensible shared-table authorization boundary. Provider metadata is untrusted data and cannot establish tenant identity.

## Decision

Shared-table deployments must provide a trusted local `tenant_scope` selected after host authentication and authorization. The lifecycle business key is `(tenant_scope, endpoint_alias, remote_batch_id)`. Package reads and writes bind the validated scope transaction-locally and PostgreSQL row-level security is enabled and forced.

The existing `DurableBatchAPIClient` remains source compatible under the explicit `standalone` scope. Shared deployments use `TenantDurableBatchAPIClient` and its tenant-qualified recorder seam.

Legacy rows are backfilled to `standalone`. Owner enforcement may be relaxed only inside the same atomic SQL statement that performs the backfill and restores `FORCE ROW LEVEL SECURITY`.

## Consequences

Embedding hosts must derive tenant scope from a trusted identity boundary and use application roles that are neither superusers nor `BYPASSRLS`. Provider and transport values cannot select scope. The tenant-qualified key allows identical provider identifiers in separate tenants without collision.

Rollback to the prior two-column key requires first proving that no endpoint/provider pair exists in multiple tenants. Packaged and deployable schemas must remain exact mirrors, and schema reapplication must be idempotent.
