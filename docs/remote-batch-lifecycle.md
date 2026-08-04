# Durable remote batch lifecycle

`DurableBatchAPIClient` records successful provider batch creation, polling, and
accepted cancellation transitions in PostgreSQL. It is intended for operators
who need restart-safe reconciliation, a durable current-state projection, and a
recoverable remote identifier when a provider operation succeeds but local
persistence fails.

The durable client is opt-in. `BatchAPIClient` remains available for hosts that
already own lifecycle state, ordering, or transaction coordination.

## Data model

The packaged schema creates `llm_remote_batch_jobs`. Every row is uniquely
identified by `(endpoint_alias, remote_batch_id)`, so remote identifiers do not
need to be globally unique across configured gateway aliases.

Endpoint aliases are trimmed, must be NUL-free, and are limited to at most 128
characters before an observation order is reserved, credentials are resolved,
or provider I/O starts. Remote file and batch identifiers follow the supported
gateway path contract: at most 256 ASCII characters, beginning with an
alphanumeric character and then using only letters, digits, dot, underscore,
colon, or hyphen. Caller-provided batch identifiers are validated before
reservation. Provider-returned batch identifiers are validated before any
lifecycle recorder receives them. These application checks align with the
PostgreSQL storage constraints and prevent avoidable
remote-success/local-persistence split-brain failures.

Only curated operational fields are persisted:

- remote and input file identifiers;
- endpoint and provider status;
- output and error file identifiers;
- total, completed, and failed request counts;
- bounded provider metadata when it is valid JSON;
- a database-owned observation order;
- first-seen, last-observed, terminal, and updated timestamps.

The table is a mutable current-state projection, not append-only audit history.
Hosts that require evidentiary transition history must also emit immutable,
tenant-attributed audit events to their central audit service or event store.

Provider metadata, including values such as `tenant_id`, is untrusted descriptive
data and is not an authorization or tenant-isolation boundary. A multi-tenant
host must select a tenant-scoped database, schema, endpoint alias, row-level
policy, or surrounding service boundary before invoking this client. It must
never authorize lifecycle reads or writes using provider-echoed metadata.

Arbitrary provider response fields are discarded. Counts are normalized to
non-negative integers. Invalid optional values become deterministic safe
defaults rather than ambiguous database values. Persisted total, completed, and
failed counters are monotonic: the atomic update uses PostgreSQL `GREATEST`, so a
newer sparse poll or cancellation response cannot erase known progress.

Provider metadata is canonicalized as sorted compact JSON with non-finite
numbers disabled. Cyclic, non-serializable, non-finite, or greater-than-64-KiB
UTF-8 metadata is stored as the empty object. This limit applies to the
canonical JSON representation, not the source Python object.

## Global observation ordering

Before every durable create, poll, or cancellation request, the client reserves
a value from `llm_remote_batch_observation_sequence`. PostgreSQL sequence values
are shared across client instances and are not reused after transaction rollback.
A failed request may therefore leave a harmless gap.

The reservation adds one PostgreSQL round trip before each durable provider
operation. This is deliberate: it establishes request order before network
latency can reorder responses. A poll that starts earlier but finishes later
retains its lower order and cannot overwrite a later-started poll.

Persistence uses one PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` statement.
The conflict identity is the endpoint alias plus remote batch identifier, and an
existing row is updated only when the incoming `observation_order` is strictly
greater than the stored order. There is no read-before-write race.

## Terminal-state integrity

The terminal statuses are `completed`, `failed`, `expired`, and `cancelled`.
Once one is stored, a later observation may update the row only when it carries
the same terminal status. This permits delayed output/error identifiers, final
counts, or metadata to enrich the row while preventing a terminal job from
returning to a non-terminal or different terminal state. The first terminal
timestamp is retained.

## Fail-closed recovery behavior

### Reservation failure

If the database order cannot be reserved, the durable client raises
`GatewayError` before provider I/O. Its structured `response_data` includes:

- `operation`;
- `phase` set to `reservation`;
- `endpoint_alias`;
- `batch_id` when it was known before the request;
- the reservation exception type.

No side-effecting provider request has occurred in this case.

### Persistence failure after remote success

If a remote operation succeeds but its observation cannot be persisted, the
client raises `GatewayError` with:

- `operation`;
- `phase` set to `persistence`;
- `endpoint_alias`;
- `batch_id` when known;
- `observation_order`;
- the persistence exception type.

This recovery path also covers a successful provider response containing a
batch identifier outside the supported gateway contract. The untrusted value is
included as reconciliation evidence but is never passed to a custom lifecycle
recorder or PostgreSQL.

The remote batch identifier and order remain available for operator
reconciliation. The client does not replay side-effecting provider POST
operations and does not pretend that an unpersisted transition succeeded
locally.

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
        metadata={"batch_description": "nightly-evaluation"},
    )
    current = await client.get_batch_status(created["id"], "default")
```

Tests and embedded hosts can inject compatible seams:

```python
DurableBatchAPIClient(
    dsn,
    provider,
    observation_reserver=lambda dsn: 42,
    lifecycle_recorder=lambda dsn, alias, batch, order: None,
)
```

A custom reserver must return a positive non-boolean integer. A custom recorder
receives the exact order reserved before the corresponding provider operation.

## Provider compatibility

The stored field set follows the core Batch object fields documented by OpenAI:
`id`, `input_file_id`, `endpoint`, `status`, `output_file_id`, `error_file_id`,
`request_counts`, and object-valued `metadata`. OpenAI-compatible gateways may
omit optional fields; the normalization rules above preserve a stable local
contract. Gateways that emit resource identifiers outside the documented ASCII
path-segment contract require an adapter before durable lifecycle persistence.

## References

OpenAI. (n.d.). *Batch API reference*. OpenAI Platform. Retrieved August 4,
2026, from https://platform.openai.com/docs/api-reference/batch/object

PostgreSQL Global Development Group. (2026). *Conditional expressions*. In
*PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/current/functions-conditional.html

PostgreSQL Global Development Group. (2026). *INSERT*. In *PostgreSQL 18
documentation*. https://www.postgresql.org/docs/current/sql-insert.html

PostgreSQL Global Development Group. (2026). *Sequence manipulation functions*.
In *PostgreSQL 18 documentation*.
https://www.postgresql.org/docs/current/functions-sequence.html
