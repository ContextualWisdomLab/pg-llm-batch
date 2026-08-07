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

## Export more than one bounded page

Use keyset pagination rather than `OFFSET` when an operator needs to walk older
audit evidence for export to separately governed retention storage:

```python
before = None
while True:
    page = store.list_audit_event_page(
        "invoice-worker",
        "batch-123",
        "default",
        before_audit_event_id=before,
        limit=500,
    )
    export_to_governed_storage(page.events)
    before = page.next_before_audit_event_id
    if before is None:
        break
```

`before_audit_event_id` is either `None` or a strict positive PostgreSQL `BIGINT`
identity. The query requests at most `limit + 1` rows; the extra row is used only
to determine whether a continuation exists. At most `limit` events are exposed.
The next cursor, when present, is exactly the final returned event identity, and
the following query uses `checkpoint_audit_event_id < before_audit_event_id`.
Rows inserted later with larger identities therefore cannot shift rows already
walked or create the duplicate/skip behavior associated with offset pagination.

This is **not** a multi-page database snapshot. Package-owned calls may observe
changes committed between page requests. A caller that requires all pages from
one PostgreSQL snapshot should start a caller-owned `REPEATABLE READ` or stricter
transaction and repeatedly call `list_audit_event_page_in_transaction()` on that
same cursor. PostgreSQL documents that `REPEATABLE READ` keeps statements in the
transaction on the snapshot established by its first query. The package does not
silently change caller transaction isolation.

The cursor is a navigation boundary, not evidence of completeness, authenticity,
retention, or non-repudiation. Sequence identities can contain gaps and commit
order need not equal identity allocation order. An export consumer must persist
its own export receipt or manifest if it needs evidence that a particular export
set was delivered to immutable storage. A later row that was not visible during
an earlier read belongs to a later export/reconciliation pass.

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
signed/hash-chained evidence system. Stable bounded pagination makes that export
operationally tractable but does not itself strengthen the database tamper model.

## Standards and evidence

See [ADR 0009](adr/0009-append-only-checkpoint-audit-trail.md) for the base audit
decision, [ADR 0010](adr/0010-bounded-checkpoint-audit-export-pagination.md) for
the export pagination boundary, and
[the export assurance record](doctoring/checkpoint-audit-export-pagination.md)
for failure modes, concurrency semantics, verification evidence, and APA 7
references to NIST SP 800-53 Rev. 5 AU-9 and PostgreSQL 18 transaction-isolation
documentation.
