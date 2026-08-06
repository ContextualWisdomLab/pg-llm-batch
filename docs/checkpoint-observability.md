# Durable checkpoint observability

`OpenTelemetryCheckpointStore` is an optional wrapper for
`PostgresBatchResultCheckpointStore` or a compatible host-owned checkpoint
store. It emits one span, one completed-operation count, and one duration
measurement for each public load or save call. It does not install or configure
OpenTelemetry.

## Host setup

Install and configure the OpenTelemetry API, SDK, processors, and exporters in
the embedding service. Then pass the host-owned tracer and meter explicitly:

```python
from opentelemetry import metrics, trace

from pg_llm_batch import (
    OpenTelemetryCheckpointStore,
    PostgresBatchResultCheckpointStore,
)

checkpoint_store = PostgresBatchResultCheckpointStore(
    "postgresql://application-role@database/operations",
    tenant_scope="tenant-a",
)
observed_checkpoints = OpenTelemetryCheckpointStore(
    checkpoint_store,
    tracer=trace.get_tracer("buyer.application"),
    meter=metrics.get_meter("buyer.application"),
)

current = observed_checkpoints.load(
    "result-worker",
    "batch-123",
    "default",
)
```

The wrapper delegates all arguments and returns unchanged. Use
`load_in_transaction()` and `save_in_transaction()` exactly as on the underlying
store when checkpoint advancement must share a caller-owned PostgreSQL
transaction with local business effects. The wrapper does not commit or roll
back that cursor.

## Signal contract

Spans:

- `pg_llm_batch.checkpoint.load`
- `pg_llm_batch.checkpoint.save`

Metrics:

- `pg_llm_batch.checkpoint.operation.count`, unit `{operation}`
- `pg_llm_batch.checkpoint.operation.duration`, unit `s`

Fixed attributes:

- `db.system.name=postgresql` on spans
- `pg_llm_batch.checkpoint.operation=load|save`
- `pg_llm_batch.checkpoint.transaction_owner=package|caller`
- `pg_llm_batch.checkpoint.outcome=success|conflict|validation_error|error`
- `error.type=checkpoint_conflict|validation_error|internal_error` on failures

Success omits `error.type`. The duration is measured with a monotonic clock and
is never negative.

## Confidentiality and cardinality

Package-owned telemetry never contains tenant scope, checkpoint consumer name,
remote batch identifier, endpoint alias, provider file identifier, checkpoint
digest, database cursor, DSN, provider payload, exception message, exception
object, or dynamic exception class name. Do not add those values as metric
attributes in host wrappers; they create confidentiality and unbounded-cardinality
risk. Use access-controlled logs or a separately reviewed audit store when an
operator must reconcile a specific durable identity.

Automatic exception recording and automatic status-on-exception are disabled.
The wrapper supplies `(None, None, None)` when closing the span context so the
application exception is not handed to observer code through context-manager
arguments.

## Failure behavior

Telemetry is best effort. Ordinary tracer, meter, span, exporter-surface, clock,
and telemetry-originated cancellation failures are contained. They do not change
the checkpoint result, exact exception object, compare-and-swap decision,
transaction owner, commit, or rollback behavior. Non-cancellation process-control
exceptions remain outside this observer-failure guarantee.

A caller-owned transaction span measures only the package method call. It does
not prove that the surrounding transaction later committed, replicated, or
completed downstream effects. Observe those boundaries in the embedding service.

## Rollback

Remove `OpenTelemetryCheckpointStore` from service composition and call the
underlying checkpoint store directly. No schema, migration, persisted row,
checkpoint digest, or package version needs rollback.
