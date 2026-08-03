# Database integrity migration

The schema enforces identities used by idempotent preparation and JOIN-only
payload reconstruction.

## Enforced relationships

- Every `llm_batch_files.queue_uuid` references an existing `llm_queues` row.
- A batch has at most one file for each `part_index`.
- `file_path` and non-null `payload_file_id` identify one batch file each.
- A request appears at most once inside a given payload, while a later retry may
  place the same request in a different payload.
- A payload has at most one line for each `sequence_no`.
- Non-null `llm_batches.input_file_path` values are unique because the value is
  accepted as an alternate batch lookup key.

## Existing deployments

`db.apply_schema()` drops the legacy random default from
`llm_batch_files.queue_uuid`. Before adding the queue foreign key, it counts
orphaned file rows. The migration fails with PostgreSQL foreign-key SQLSTATE
`23503` when orphans exist; it never deletes data or silently chooses a queue.
Repair the affected rows and run the idempotent schema application again.

Unique indexes likewise fail visibly when legacy duplicates exist. Resolve the
duplicate business identity rather than discarding an arbitrary row. Useful
preflight queries include:

```sql
SELECT input_file_path, COUNT(*)
FROM llm_batches
WHERE input_file_path IS NOT NULL
GROUP BY input_file_path
HAVING COUNT(*) > 1;

SELECT batch_uuid, part_index, COUNT(*)
FROM llm_batch_files
GROUP BY batch_uuid, part_index
HAVING COUNT(*) > 1;

SELECT payload_file_id, request_uuid, COUNT(*)
FROM llm_jsonl_lines
GROUP BY payload_file_id, request_uuid
HAVING COUNT(*) > 1;
```

The partial preparation index targets queued requests whose
`batch_file_uuid IS NULL`. The status index supports operational scans by state
and last update time. The global request lookup index remains available for
retry history queries; only the redundant payload-only index is removed because
the unique `(payload_file_id, sequence_no)` index already covers that prefix.
