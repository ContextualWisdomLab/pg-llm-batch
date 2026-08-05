# Tenant-Scoped Durable Lifecycle Isolation Design

## Context

`DurableBatchAPIClient` persists provider lifecycle snapshots in
`llm_remote_batch_jobs` under the compound identity
`(endpoint_alias, remote_batch_id)`. That is sufficient for a single-tenant
installation, but it does not provide a first-class tenant boundary for an
embedded MSA deployment. The current operator documentation correctly warns
that provider metadata such as `tenant_id` is descriptive data and must not be
used for authorization, yet the package does not offer a tenant-bearing client,
a tenant-qualified database identity, or a fail-closed row policy.

This gap is commercially material. Two tenants can use the same endpoint alias
and receive the same provider-local batch identifier. Without a trusted local
tenant key, one row can collide with another tenant's lifecycle projection.
Direct SQL access also has no package-owned row-isolation policy, so a host must
reimplement the security boundary correctly in every embedding.

## Goals

- Add a trusted local `tenant_scope` to the durable lifecycle identity.
- Preserve standalone operation through an explicit `standalone` scope.
- Provide a multi-tenant client whose tenant scope is required and validated at
  construction before reservation, credential resolution, provider I/O, or
  persistence.
- Make PostgreSQL row access fail closed when no transaction-local tenant scope
  has been established.
- Force the table owner through row-level security while documenting that
  superusers and `BYPASSRLS` roles remain outside the guarantee.
- Keep the existing `DurableBatchAPIClient` and custom recorder signature
  source-compatible for single-tenant consumers.
- Provide tenant-scoped read helpers so operators do not need to construct
  authorization-sensitive SQL.
- Migrate existing rows deterministically to `standalone` without deleting,
  re-keying, or silently merging lifecycle data.
- Keep all database object names descriptive multi-word `snake_case`.
- Retain 100% production statement, branch, and public-docstring coverage.

## Non-goals

- Treating provider-returned metadata, JWT claims, HTTP headers, or endpoint
  aliases as a tenant authority.
- Provisioning tenants, authenticating callers, or mapping external identities
  to tenant scopes.
- Adding append-only audit history in this slice. The existing table remains a
  current-state projection; immutable audit events are a separate bounded
  follow-up.
- Applying tenant scope to queue, request, token-count, or payload tables.
- Supporting superuser or `BYPASSRLS` isolation. PostgreSQL explicitly exempts
  those roles from row security.
- Introducing schema-per-tenant or database-per-tenant deployment automation.

## Approaches considered

### 1. Continue requiring every host to wrap the package

A host can already isolate tenants with separate databases, schemas, roles, or
service instances. This preserves package simplicity but leaves a repeated,
high-consequence integration task to every buyer and does not prevent accidental
cross-tenant collisions in the shared-table deployment. Rejected as the sole
commercial contract.

### 2. Add separate enterprise-only tenant tables and client

A second table could avoid changing the existing projection. It would duplicate
lifecycle constraints, upsert logic, indexes, migrations, and operational
queries. Drift between standalone and tenant tables would become a permanent
maintenance and acquisition risk. Rejected.

### 3. Extend the existing projection with a trusted tenant scope and RLS — selected

Add `tenant_scope` to `llm_remote_batch_jobs`, migrate legacy rows to
`standalone`, replace the old unique key with
`(tenant_scope, endpoint_alias, remote_batch_id)`, and enable forced row-level
security. Package helpers set a validated transaction-local PostgreSQL setting
before every lifecycle read or write. The existing client uses the explicit
`standalone` scope; a new `TenantDurableBatchAPIClient` requires a caller-supplied
scope and uses tenant-aware persistence.

This approach keeps one authoritative lifecycle model, preserves the standalone
API, and gives embedded deployments a secure default-deny row boundary.

## Trusted tenant-scope contract

`tenant_scope` is a local authorization attribute. It must be supplied by a
trusted host boundary after authentication and authorization. Provider response
fields are never consulted to choose it.

The accepted syntax is 1-128 ASCII characters:

```text
[A-Za-z0-9][A-Za-z0-9._:-]{0,127}
```

The validator does not trim or coerce values. Leading/trailing whitespace,
Unicode, controls, path separators, percent escapes, empty values, booleans,
and over-limit values fail before external effects. Exact preservation makes
security logs and database identities unambiguous.

The package exposes:

```python
DEFAULT_TENANT_SCOPE = "standalone"


def validate_tenant_scope(value: object) -> str:
    """Validate one trusted local tenant scope without coercion."""
```

## Database model and migration

For new installations, `llm_remote_batch_jobs` includes:

```sql
tenant_scope TEXT NOT NULL DEFAULT 'standalone'
    CONSTRAINT ck_llm_remote_batch_jobs_tenant_scope
    CHECK (tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
```

The unique constraint becomes:

```sql
CONSTRAINT uq_llm_remote_batch_jobs_tenant_endpoint_id
    UNIQUE (tenant_scope, endpoint_alias, remote_batch_id)
```

Existing installations are migrated idempotently:

1. add `tenant_scope` when absent;
2. backfill only null rows to `standalone`;
3. set the default and `NOT NULL` contract;
4. add the named syntax constraint when absent;
5. drop the superseded two-column unique constraint;
6. add the tenant-qualified unique constraint when absent;
7. create the tenant-qualified status/observation index;
8. enable and force row-level security;
9. replace the package-owned policy with the reviewed exact expression.

No row is deleted. The old unique key guarantees that the deterministic
backfill cannot create a duplicate triple.

## Row-level security boundary

The package policy applies to `PUBLIC` and uses the transaction-local setting:

```sql
USING (
    tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
)
WITH CHECK (
    tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
)
```

When the setting is missing, `current_setting(..., true)` returns `NULL`; the
comparison does not evaluate to true, so access is denied. Both
`ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` are required.

Every package lifecycle database transaction begins with:

```sql
SELECT set_config('pg_llm_batch.tenant_scope', %s, true)
```

The `true` argument limits the setting to the current transaction and prevents
scope leakage through a pooled connection. The value is a bound parameter, not
dynamic SQL.

The guarantee does not include PostgreSQL superusers or roles with `BYPASSRLS`.
Production service roles must be `NOSUPERUSER NOBYPASSRLS`, and operators must
reserve bypass roles for controlled administration.

## Persistence interfaces

The existing function remains source-compatible:

```python
def persist_remote_batch_state(
    dsn: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
```

It delegates to one internal implementation with
`tenant_scope=DEFAULT_TENANT_SCOPE`.

The tenant-aware entry point is explicit:

```python
def persist_tenant_remote_batch_state(
    dsn: str,
    tenant_scope: str,
    endpoint_alias: str,
    provider_batch: Mapping[str, Any],
    observation_order: int,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
```

Both return the normalized snapshot including `tenant_scope`. The upsert conflict
key and every update reference use the tenant-qualified identity.

Tenant-scoped reads are exposed through:

```python
def get_tenant_remote_batch_state(
    dsn: str,
    tenant_scope: str,
    endpoint_alias: str,
    remote_batch_id: str,
) -> dict[str, Any] | None:
    """Return one lifecycle projection visible to the validated tenant scope."""
```

A standalone convenience wrapper delegates with the default scope.

## Client interfaces

`DurableBatchAPIClient` retains its constructor and `LifecycleRecorder`
signature. Its default recorder writes to `standalone`. Existing injected
recorders continue receiving `(dsn, endpoint_alias, provider_batch,
observation_order)`.

A new subclass requires tenant scope:

```python
TenantLifecycleRecorder = Callable[
    [str, str, str, Mapping[str, Any], int],
    Any,
]


class TenantDurableBatchAPIClient(DurableBatchAPIClient):
    """Durable client with a required trusted local tenant scope."""
```

Its constructor validates `tenant_scope` synchronously and stores the exact
value. It overrides only the recorder dispatch boundary, passing
`(dsn, tenant_scope, endpoint_alias, provider_batch, observation_order)` to the
tenant recorder. Reservation remains global and provider behavior remains
unchanged. Invalid scope therefore fails before a sequence value, secret lookup,
or network call.

## Error and privacy contract

Tenant scope is a local operational identifier and may appear in structured
reservation or persistence recovery evidence. Provider content, credentials,
URLs, prompts, metadata values, and unsupported provider identifiers remain
excluded.

Validation errors use the bounded field name `tenant_scope` and the existing
`ValidationError` structure. RLS-denied reads return no row through the package
helper. Database permission/configuration failures remain explicit database
exceptions; the package does not reinterpret them as absence.

## Testing

Tests are introduced before production changes and cover:

- strict accepted and rejected tenant-scope boundaries;
- invalid tenant scope failing before observation reservation and provider I/O;
- legacy `DurableBatchAPIClient` using the exact `standalone` scope;
- tenant client recorder propagation without changing the old recorder seam;
- tenant-qualified conflict SQL and snapshot output;
- transaction-local `set_config` occurring before each read or write;
- schema backfill, constraint replacement, tenant-qualified indexes, RLS enable,
  forced-owner enforcement, and default-deny policy expressions;
- identical provider IDs persisting under two tenant scopes without identity
  collision;
- tenant-scoped reads binding all identity fields;
- idempotent schema application and exact deployable-schema mirror;
- live PostgreSQL isolation where tenant A cannot read tenant B through package
  helpers;
- Python 3.10, 3.12, and 3.14 compatibility;
- 100% production statement, branch, and public-docstring coverage;
- package, Compose, container, SAST, security, and review gates.

## Documentation and interoperability

`README.md`, `docs/remote-batch-lifecycle.md`, `ARCHITECTURE.md`, `AGENTS.md`,
`CLAUDE.md`, `CHANGELOG.md`, and a dedicated doctoring record describe:

- standalone versus tenant-scoped operation;
- the trusted host responsibility for choosing tenant scope;
- pooled-connection transaction scoping;
- PostgreSQL role requirements and bypass limitations;
- migration and rollback considerations;
- compatibility with central CWL services and MSA embedding.

The feature introduces no LLM call, model routing, psychometric arithmetic, UI,
or Figma requirement.

## References

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Revision 5, including
Release 5.2.0 updates). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

OWASP Foundation. (n.d.). *Multi-tenant security cheat sheet*. OWASP Cheat Sheet
Series. Retrieved August 5, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html

PostgreSQL Global Development Group. (2026). *Row security policies*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/ddl-rowsecurity.html

PostgreSQL Global Development Group. (2026). *System administration functions*.
In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-admin.html
