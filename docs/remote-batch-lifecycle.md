# Durable remote batch lifecycle

`DurableBatchAPIClient` records successful provider batch creation, polling, and
accepted cancellation transitions in PostgreSQL. It is intended for operators
who need restart-safe reconciliation, acquisition-grade audit evidence, and a
recoverable remote identifier when a provider operation succeeds but local
persistence fails.

## Data model

The packaged schema creates `llm_remote_batch_jobs`. Every row is uniquely
identified by `(endpoint_alias, remote_batch_id)` because provider identifiers
must not be assumed globally unique across gateways or tenants.

Only curated operational fields are persisted:

- remote and input file identifiers;
- endpoint and provider status;
- output and error file identifiers;
- total, completed, and failed request counts;
- provider metadata when it is a JSON object;
- first-seen, last-observed, terminal, and updated timestamps.

Arbitrary provider response fields are discarded to reduce accidental storage
of unreviewed content. Counts are normalized to non-negative integers. Invalid
optional values become deterministic safe defaults rather than being written as
ambiguous database values.

## Concurrency and stale observations

Persistence uses one PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` statement.
The conflict identity is the endpoint alias plus remote batch identifier. The
update predicate accepts only observations whose `last_observed_at` is at least
as recent as the stored observation, so a delayed poll cannot regress a newer
status. The first terminal timestamp is retained.

PostgreSQL documents `ON CONFLICT DO UPDATE` as the atomic alternative to a
unique-constraint failure for the proposed row. This is the concurrency
primitive used by the lifecycle store; no read-before-write race is introduced.

## Fail-closed recovery behavior

A successful remote operation followed by a local persistence failure raises a
`GatewayError`. Its structured `response_data` includes:

- `operation`;
- `endpoint_alias`;
- `batch_id` when known;
- the persistence exception type.

The remote batch identifier is therefore available for operator reconciliation.
The client does not retry side-effecting provider POST operations and does not
pretend that an unpersisted transition succeeded locally.

## Usage

Apply the idempotent schema first:

```python
from pg_llm_batch import db

db.apply_schema(dsn)
```

Construct the durable client with the same credential seam as the base client:

```python
from pg_llm_batch import DurableBatchAPIClient
from pg_llm_batch.batch_api_client import config_credentials_provider
from pg_llm_batch.config import PostgresConfigStore, SecretStore

provider = config_credentials_provider(
    PostgresConfigStore(dsn),
    SecretStore(dsn),
)

async with DurableBatchAPIClient(dsn, provider) as client:
    created = await client.create_batch_job(
        input_file_id="file-provider-id",
        endpoint_alias="default",
        endpoint="/v1/responses",
        metadata={"tenant_id": "tenant-a"},
    )
    current = await client.get_batch_status(created["id"], "default")
```

Hosts that already own lifecycle persistence may continue using
`BatchAPIClient`. Tests and embedded hosts can inject a compatible
`lifecycle_recorder(dsn, endpoint_alias, provider_batch)` into
`DurableBatchAPIClient`.

## Provider compatibility

The stored field set follows the core Batch object fields documented by OpenAI:
`id`, `input_file_id`, `endpoint`, `status`, `output_file_id`, `error_file_id`,
and `request_counts`. OpenAI-compatible gateways may omit optional fields; the
normalization rules above preserve a stable local contract.

## References

OpenAI. (2026). *Batch API reference*. OpenAI Platform documentation.
https://platform.openai.com/docs/api-reference/batch/object

PostgreSQL Global Development Group. (2026). *INSERT*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/current/sql-insert.html
