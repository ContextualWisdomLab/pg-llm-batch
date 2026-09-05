# Durable remote batch lifecycle

`pg-llm-batch` offers two opt-in durable clients for operators who need
restart-safe provider reconciliation:

- `DurableBatchAPIClient` stores lifecycle state in the explicit
  `standalone` tenant scope while preserving the original four-argument
  recorder seam.
- `TenantDurableBatchAPIClient` requires a trusted local `tenant_scope` and
  stores lifecycle state under a tenant-qualified identity suitable for a
  shared-table MSA deployment.

`BatchAPIClient` remains available for hosts that already own lifecycle state,
ordering, or persistence. The durable table is a mutable current-state
projection, not append-only audit history. Hosts that require evidentiary
transition history must also emit immutable, tenant-attributed audit events to
their central audit service or event store.

## Trust model

`tenant_scope` is selected by the embedding host only after authentication and
authorization. It is never derived from provider metadata, endpoint aliases,
remote resource identifiers, request payloads, model output, or transport
headers.

The exact accepted syntax is:

```text
[A-Za-z0-9][A-Za-z0-9._:-]{0,127}
```

The value is not trimmed or coerced. Empty values, whitespace, Unicode,
controls, path separators, percent escapes, booleans, and values longer than
128 characters fail before observation reservation, credential resolution,
provider I/O, or database access.

### What PostgreSQL RLS does and does not protect

Every package-managed lifecycle transaction binds the validated scope with a
parameterized, transaction-local call:

```sql
SELECT set_config('pg_llm_batch.tenant_scope', $1, true);
```

The row policy compares `tenant_scope` with
`current_setting('pg_llm_batch.tenant_scope', true)`. A missing setting produces
no matching policy row, so ordinary package access fails closed. The local flag
also prevents a scope from surviving transaction completion on a pooled
connection.

For lifecycle-outbox migration 0008, the tenant predicate's operator/function
authority does not depend on session `search_path`. Canonical policy v2 binds
text equality as `OPERATOR(pg_catalog.=)` and resolves the setting with
`pg_catalog.current_setting` in both `USING` and `WITH CHECK`. The policy name
itself is not accepted as proof: migration 0008 checks `pg_policy` for
all-command permissive `PUBLIC` scope and the canonical stored `USING` and
`WITH CHECK` expression trees. A same-name v2 with semantic drift is repaired;
an unknown policy name aborts migration rather than being silently retained or
deleted; and the resulting v2 is verified again before earlier v1/legacy names
are removed. A semantically current v2 avoids repeated policy DDL on normal
reapply.

This custom PostgreSQL setting is a **trusted application boundary**, not a
credential. PostgreSQL accepts two-part custom option names, and a database role
that can execute arbitrary SQL can call `set_config` with an arbitrary tenant
scope. Consequently, this RLS policy is not a substitute for preventing SQL
injection, restricting direct SQL access, authenticating callers, or mapping an
external identity to an authorized tenant. Do not expose the lifecycle database
role or a generic SQL console to untrusted tenants. Use parameterized package
helpers or a separately reviewed security-definer/role-mapping layer when raw
SQL access is required.

Production application identities must be `NOSUPERUSER NOBYPASSRLS`. PostgreSQL
superusers and roles with `BYPASSRLS` always bypass row security. Table owners
are included only because the schema applies `FORCE ROW LEVEL SECURITY`.
Administrative bypass roles must not be used by ordinary services.

## Data model

The durable business identity is:

```text
(tenant_scope, endpoint_alias, remote_batch_id)
```

This allows two authorized tenants to use the same endpoint alias and receive
the same provider-local batch identifier without colliding.

Endpoint aliases are trimmed, NUL-free, and limited to 128 characters. Remote
file and batch identifiers are limited to 256 ASCII characters, begin with an
alphanumeric character, and then use only letters, digits, dot, underscore,
colon, or hyphen. Caller-provided identifiers are validated before reservation,
credential resolution, or provider I/O. Provider-returned identifiers are
validated before a custom recorder or PostgreSQL sees them.

Only curated operational fields are stored:

- tenant scope, endpoint alias, and remote batch identifier;
- input, output, and error file identifiers;
- provider endpoint and status;
- total, completed, and failed request counts;
- bounded canonical provider metadata;
- a database-owned observation order;
- first-seen, last-observed, terminal, and updated timestamps.

Arbitrary provider fields are discarded. Counts become non-negative integers.
Provider metadata is serialized as sorted compact JSON with non-finite numbers
disabled and a 64 KiB UTF-8 limit. Cyclic, non-serializable, invalid-Unicode,
NUL-bearing, non-finite, or oversized metadata becomes the empty object.

## Ordering and state reconciliation

Before every durable create, poll, or accepted cancellation request, the client
reserves a value from `llm_remote_batch_observation_sequence`. PostgreSQL
sequence values are global and are not reused after rollback, so failed requests
leave harmless gaps.

Persistence uses one parameterized
`INSERT ... ON CONFLICT (tenant_scope, endpoint_alias, remote_batch_id) DO
UPDATE` statement. An existing row changes only when the incoming
`observation_order` is strictly newer. `GREATEST` keeps request counters
monotonic, and sparse later responses cannot erase known file identifiers or
metadata.

The terminal statuses are `completed`, `failed`, `expired`, and `cancelled`.
Once one is stored, a later observation can enrich the row only when it carries
the same terminal status. The first terminal timestamp is retained.

## Schema migration and rollback

Existing rows are backfilled to the exact `standalone` scope without deletion,
identity merging, or silent re-parenting. The previous two-column unique
constraint is replaced with the tenant-qualified key. The temporary owner
transition, backfill, constraint replacement, and restoration of forced RLS run
inside one PostgreSQL anonymous block so psql autocommit cannot commit an
intermediate owner-bypass state.

The packaged schema and the Docker initialization schema are byte-for-byte
mirrors and support idempotent reapplication. The migration enables and forces
RLS, converges the package-owned tenant policy by catalog semantics, and installs
the tenant-qualified operational index. Unknown lifecycle-outbox policy names
are a fail-closed migration finding rather than an implicit extension point.

Rollback to the former `(endpoint_alias, remote_batch_id)` key is unsafe until
an operator proves that no pair appears in more than one tenant scope. Before a
rollback, also provide an explicit replacement authorization boundary for every
direct lifecycle query; otherwise existing package users may either lose access
or reintroduce cross-tenant collisions.

Existing SQL integrations are operationally affected: once RLS is enabled,
direct queries that do not establish an authorized transaction-local scope see
no lifecycle rows. Migrate those consumers to the package read helpers or a
reviewed tenant-binding database interface before deploying this schema.

## Public persistence and read helpers

Standalone code keeps the original API:

```python
from pg_llm_batch import (
    DurableBatchAPIClient,
    get_remote_batch_state,
)

async with DurableBatchAPIClient(dsn, credentials_provider) as client:
    created = await client.create_batch_job(
        input_file_id="file-provider-id",
        endpoint_alias="default",
        endpoint="/v1/responses",
    )

state = get_remote_batch_state(dsn, "default", created["id"])
```

Shared-table hosts use the tenant-aware API:

```python
from pg_llm_batch import (
    TenantDurableBatchAPIClient,
    get_tenant_remote_batch_state,
    persist_tenant_remote_batch_state,
)

# tenant_scope must come from the host's authenticated authorization context.
async with TenantDurableBatchAPIClient(
    dsn,
    credentials_provider,
    tenant_scope="customer-42",
) as client:
    created = await client.create_batch_job(
        input_file_id="file-provider-id",
        endpoint_alias="default",
        endpoint="/v1/responses",
        metadata={"batch_description": "nightly-evaluation"},
    )

state = get_tenant_remote_batch_state(
    dsn,
    "customer-42",
    "default",
    created["id"],
)
```

The explicit persistence helper is intended for reviewed adapters and recovery
tools:

```python
persist_tenant_remote_batch_state(
    dsn,
    "customer-42",
    "default",
    provider_batch,
    observation_order,
)
```

Do not accept `tenant_scope` from the provider response supplied to that helper.

## Compatible custom seams

`DurableBatchAPIClient` keeps the original recorder contract:

```python
DurableBatchAPIClient(
    dsn,
    credentials_provider,
    observation_reserver=lambda dsn: 42,
    lifecycle_recorder=lambda dsn, alias, batch, order: None,
)
```

`TenantDurableBatchAPIClient` uses a separate explicit recorder seam so tenant
identity cannot be silently dropped:

```python
TenantDurableBatchAPIClient(
    dsn,
    credentials_provider,
    tenant_scope="customer-42",
    observation_reserver=lambda dsn: 42,
    tenant_lifecycle_recorder=(
        lambda dsn, tenant, alias, batch, order: None
    ),
)
```

A custom reserver must return a positive non-boolean integer. A custom recorder
receives the exact order reserved before the corresponding provider operation.

## Fail-closed recovery behavior

If observation reservation fails, the client raises `GatewayError` before
provider I/O. If a provider operation succeeds but validation or persistence
fails, it raises `GatewayError` with bounded recovery metadata: operation,
phase, validated endpoint alias, trusted batch identifier when available,
observation order, exception category, and tenant scope for the tenant client.
Provider payloads, credentials, URLs, metadata values, and rejected raw
identifiers are excluded.

For status polling, a present provider response identifier must exactly match
the validated requested identifier. A mismatch is rejected before a custom
recorder or PostgreSQL receives it, and only the trusted requested identifier is
retained in recovery evidence.

The client does not automatically replay side-effecting provider POST requests
and does not report an unpersisted remote transition as locally durable.

## Verification

Deterministic tests cover strict tenant syntax, pre-effect validation,
standalone recorder compatibility, tenant recorder propagation, parameterized
transaction context, tenant-qualified conflict targets and reads, malformed
database rows, migration preservation and reapplication, forced default-deny
RLS, search-path-independent lifecycle policy predicate authority, full
canonical `pg_policy` command/role/expression identity, unknown-policy
fail-closed behavior, post-create/post-repair catalog verification, exact schema
mirroring, Python 3.10/3.12/3.14 compatibility, complete public docstrings, and
100% production statement and branch coverage.

The live PostgreSQL integration test uses a `NOSUPERUSER NOBYPASSRLS` role,
persists an identical provider identifier in two tenant scopes, and proves that
a transaction bound to one scope cannot read the other scope through the
policy. This test verifies policy mechanics under the trusted package model; it
does not claim protection after arbitrary SQL execution is granted. Exact-head
runtime execution must also run migration 0008 so PostgreSQL evaluates its final
canonical `pg_policy` postcondition.

## References

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST Special Publication 800-53, Revision 5). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-53r5

MITRE. (2026). *CWE-89: Improper neutralization of special elements used in an
SQL command ('SQL injection')* (Version 4.20).
https://cwe.mitre.org/data/definitions/89.html

OpenAI. (n.d.). *Batch API reference*. OpenAI Platform. Retrieved August 5,
2026, from https://platform.openai.com/docs/api-reference/batch/object

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

PostgreSQL Global Development Group. (2026g). *System information functions and
operators*. In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/18/functions-info.html
