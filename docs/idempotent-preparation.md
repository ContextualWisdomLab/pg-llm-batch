# Idempotent batch preparation

`PostgresBatchOrchestrator.prepare_batches()` is a first-write operation for one
`llm_batches.batch_uuid`.

The persistence transaction acquires a transaction-scoped PostgreSQL advisory
lock derived from the batch UUID and locks the batch row. It then behaves as
follows:

1. When no files exist, all payloads, JSONL lines, request-to-file assignments,
   and aggregate batch counts are committed atomically.
2. A concurrent or repeated call with no new unassigned requests returns the
   already persisted `ready` and `overflow` payloads.
3. New queued requests cannot be appended after preparation. The caller receives
   a structured `ValidationError` and must create a new batch.
4. Any request-assignment count mismatch aborts the transaction, so callers never
   observe a partially prepared batch.

Requests remain in the `queued` state until submission, but receive their
`batch_file_uuid` during preparation. The preparation query selects only queued,
unassigned requests. This keeps the state machine honest while making retries
safe after process restarts, duplicate scheduler delivery, or concurrent workers.
