# Checkpoint accepted-save audit trail

`AuditedPostgresBatchResultCheckpointStore` is an opt-in extension of the durable
checkpoint store for deployments that need retained application audit evidence.
It writes one append-only `checkpoint_save_accepted` row after every successful
checkpoint save call and keeps that event in the same PostgreSQL transaction as
the checkpoint operation.

## Deploy

For an existing database, apply the audit schema after the durable checkpoint
schema:

```python
from pg_llm_batch import (
    apply_result_checkpoint_audit_schema,
    apply_result_checkpoint_schema,
)

apply_result_checkpoint_schema(POSTGRES_DSN)
apply_result_checkpoint_audit_schema(POSTGRES_DSN)
```

The bundled PostgreSQL image runs both migrations, in that order, when the
official PostgreSQL entrypoint initializes a **new** data directory. Existing
volumes are not upgraded by entrypoint scripts; run the reviewed migration or the
package helper explicitly during deployment.

Reapplying the audit migration also repairs the `recorded_at` column default to
`clock_timestamp()`. PostgreSQL `NOW()`/`CURRENT_TIMESTAMP` represent the start
of the current transaction, so a long caller-owned transaction could otherwise
stamp an accepted save with a time materially earlier than the save itself.
Existing audit rows are never rewritten; only subsequent inserts use the repaired
wall-clock event-time default.

Production application roles remain `NOSUPERUSER NOBYPASSRLS`. Tenant scope and
consumer name must come from the host's authenticated and authorized control
plane, never from provider data or model output.

## Write atomically

```python
from pg_llm_batch import AuditedPostgresBatchResultCheckpointStore

store = AuditedPostgresBatchResultCheckpointStore(
    POSTGRES_DSN,
    tenant_scope="tenant-a",
)

saved = store.save(
    "invoice-worker",
    checkpoint,
    expected_previous=previous,
)
```

`save()` commits checkpoint state and the accepted-save audit event together. If
an audit insert fails, the save transaction fails rather than committing the
checkpoint without required audit evidence.

For local record effects that must share the same PostgreSQL transaction, use
`save_in_transaction()` with the caller's cursor. The method never commits or
rolls back that cursor. Audit `recorded_at` is evaluated with PostgreSQL
`clock_timestamp()` when the accepted-save row is inserted, not when that
caller-owned transaction began.

An exact idempotent repeat produces another audit event. Audit rows describe
successful package calls, not necessarily unique durable state transitions. A
validation or compare-and-swap rejection produces no
`checkpoint_save_accepted` row.

## Read bounded evidence

```python
events = store.list_audit_events(
    "invoice-worker",
    "batch-123",
    "default",
    limit=100,
)
```

Results are newest-first and the limit is a strict integer from 1 through 1,000.
The query is tenant-qualified by the store's trusted scope and exact consumer,
endpoint, and batch key.

The event contains structured checkpoint identity and coordinates, the fixed
action, a database-generated event identity, and an insert-time database
wall-clock timestamp. It does not include provider bodies, prompts, model output,
credentials, DSNs, transport headers, or exception text.

## Export longer retained history

Use the opt-in keyset page API instead of `OFFSET` or an unbounded fetch:

```python
page = store.list_audit_event_page(
    "invoice-worker",
    "batch-123",
    "default",
    limit=250,
)

while True:
    persist_to_governed_retention(page.events)
    if page.next_before_audit_event_id is None:
        break
    page = store.list_audit_event_page(
        "invoice-worker",
        "batch-123",
        "default",
        before_audit_event_id=page.next_before_audit_event_id,
        limit=250,
    )
```

`before_audit_event_id` is `None` or a strict positive signed PostgreSQL `BIGINT`.
Each SQL request reads at most `limit + 1` rows and returns at most `limit` events.
Continuation uses `checkpoint_audit_event_id < before_audit_event_id` in strict
newest-first order. Returned rows are revalidated against the exact trusted
tenant, consumer, endpoint, and batch key before exposure.

A committed event with a larger identity between page calls cannot shift the
older continuation window. Separate package-owned calls are still separate
transactions, however, so they do not form one historic database snapshot. For
an export that must observe one PostgreSQL snapshot, begin a caller-owned
`REPEATABLE READ` or stricter transaction **before the first query** and reuse
`list_audit_event_page_in_transaction()` on that transaction's cursor.

The cursor is navigation state, not completeness, chronology, delivery,
authenticity, or non-repudiation evidence. PostgreSQL identity sequences may have
gaps and allocation order can differ from commit order. Destination credentials,
immutable/WORM storage, retention, legal hold, delivery receipts, cryptographic
manifests, and reconciliation remain host/operator responsibilities.

## Retention and rollback

The database blocks ordinary `UPDATE`, `DELETE`, and `TRUNCATE` against the audit
table. The packaged rollback refuses to drop a non-empty table across all tenant
scopes. Export, retain, reconcile, and dispose of audit evidence under the host's
legal, contractual, and operational retention policy before intentional schema
removal.

These controls are not cryptographic non-repudiation and do not protect against a
PostgreSQL owner, superuser, `BYPASSRLS` role, disabled triggers, or physical
storage administrator. Deployments that require administrator-tamper detection
should replicate or export events to separately governed immutable storage or a
signed/hash-chained evidence system.

## Standards and evidence

See [ADR 0009](adr/0009-append-only-checkpoint-audit-trail.md) for the accepted-save
audit boundary, [ADR 0011](adr/0011-bounded-checkpoint-audit-export-pagination.md)
for the pagination decision, [the audit assurance record](doctoring/checkpoint-audit-trail.md)
for audit threat-model evidence, and
[the export-pagination assurance record](doctoring/checkpoint-audit-export-pagination.md)
for keyset, isolation, operator, and APA 7 evidence. The latter records NIST SP
800-53 Rev. 5 AU-9 and PostgreSQL 18 transaction-isolation/concurrency guidance.
