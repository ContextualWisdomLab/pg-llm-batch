# Architecture

## Deployment boundary

`pg-llm-batch` remains independently deployable and embeddable. PostgreSQL owns configuration, encrypted secrets, token counting, JSONL payloads, and durable provider lifecycle state. Provider HTTP behavior remains behind `BatchAPIClient`, while host services may inject credential, observation-order, and lifecycle-persistence seams without changing provider semantics.

## Durable lifecycle tenancy

`DurableBatchAPIClient` is the backward-compatible standalone facade. `TenantDurableBatchAPIClient` requires an immutable tenant scope selected by a trusted host after authentication and authorization. The durable business identity is:

`(tenant_scope, endpoint_alias, remote_batch_id)`

Package reads and writes bind the validated scope with transaction-local `set_config('pg_llm_batch.tenant_scope', ..., true)`. PostgreSQL row-level security is enabled and forced, so missing context is default-deny for ordinary application roles. PostgreSQL superusers and roles with `BYPASSRLS` remain administrative escape hatches and must not be used as application identities.

Provider metadata, endpoint aliases, provider resource identifiers, payloads, and transport headers never select tenant authorization context.

## Migration and rollback

Legacy lifecycle rows are backfilled to `standalone` without deletion or identity merging. The prior endpoint/provider unique key is replaced by a tenant-qualified key. The owner-enforcement transition, backfill, constraint migration, and forced-RLS restoration execute in one PostgreSQL anonymous block so psql autocommit cannot commit an intermediate owner-bypass state.

Rollback to the former two-column key is unsafe until an operator proves that no `(endpoint_alias, remote_batch_id)` pair exists in more than one tenant scope. The packaged schema and Docker initialization schema are maintained as exact mirrors and must be reapplied successfully more than once.

## Modular interoperability

CWL hosts such as `contextual-orchestrator` and `naruon` supply tenant context only after their own authentication and authorization boundary. The package does not require either host and retains standalone operation. When embedded, tenant scope is a local control-plane identity and not model- or provider-returned data.

## Verification boundary

Deterministic gates cover strict tenant validation, compatibility, tenant-qualified SQL parameters, current-state reconciliation, migration idempotency, malformed database rows, default-deny policy text, schema mirroring, and 100% production statement and branch coverage. Live PostgreSQL isolation tests must use a `NOSUPERUSER NOBYPASSRLS` role and prove that identical provider identifiers in different tenants remain independently addressable and mutually invisible.
