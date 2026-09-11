# Package-owned schema ERD

## Authority

This diagram summarizes protected-main package tables from
`pg_llm_batch/schema.sql` plus the migration-owned checkpoint table from
`pg_llm_batch/migrations/0007_result_stream_checkpoints.sql`. SQL and schema
tests remain stronger authority than this picture.

Use it to see identities, foreign keys, and tenant qualification before you
write a report, a restore drill, or an embedding mapping. Do not treat the
diagram as proof that backup/restore, candidate discovery, or distributed
exactly-once processing is shipped.

## What to do next

1. Keep new database objects as two-or-more-word `snake_case` names.
2. Bind `tenant_scope` before reading `llm_remote_batch_jobs` or
   `llm_result_stream_checkpoints`.
3. Treat `llm_result_stream_checkpoints` as prefix evidence, not a distributed
   exactly-once claim.
4. Leave ACTIVE-PR recovery and reconciliation tables off this diagram until
   they exist on protected main.

## Identities

| Table | Durable identity | Notes |
| --- | --- | --- |
| `llm_remote_batch_jobs` | `tenant_scope, endpoint_alias, remote_batch_id` | Forced RLS. Provider data never selects the tenant. |
| `llm_result_stream_checkpoints` | `tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id` | Added by migration 0007. Forced RLS. |
| `llm_queues` | `queue_uuid` / unique `queue_name` | Standalone preparation owner. |
| `llm_batches` | `batch_uuid` | Child of one queue. |
| `llm_batch_file_payloads` | `file_id` | Canonical JSONL bytes in PostgreSQL. |
| `llm_batch_files` | `(batch_uuid, part_index)` | Virtual payload via `payload_file_id`. |
| `llm_requests` | `request_uuid` | Authorized prompt/result content. |
| `llm_jsonl_lines` | `(payload_file_id, sequence_no)` | JOIN-only reconstruction. |
| `llm_endpoints` | `endpoint_alias` | Configuration, not tenant authority. |
| `com_config` / `com_secrets` | `config_key` / `secret_key` | KV stores. Compatibility secrets may be plaintext. |

## Entity-relationship diagram

```mermaid
erDiagram
    com_config {
        text config_key PK
        text config_value
        timestamptz updated_at
    }

    com_secrets {
        text secret_key PK
        text secret_value
        boolean is_encrypted
        timestamptz updated_at
    }

    llm_queues {
        uuid queue_uuid PK
        text queue_name UK
        text queue_status
        timestamptz created_at
    }

    llm_batches {
        uuid batch_uuid PK
        uuid queue_uuid FK
        text batch_name
        text batch_status
        text model_name
        timestamptz created_at
    }

    llm_batch_file_payloads {
        uuid file_uuid PK
        text file_id UK
        jsonb content
        timestamptz created_at
    }

    llm_batch_files {
        uuid file_uuid PK
        uuid batch_uuid FK
        uuid queue_uuid FK
        text payload_file_id FK
        int part_index
    }

    llm_requests {
        uuid request_uuid PK
        uuid batch_uuid FK
        uuid batch_file_uuid FK
        text user_prompt
        text response_content
        text request_status
    }

    llm_jsonl_lines {
        uuid line_uuid PK
        text payload_file_id FK
        uuid request_uuid FK
        int sequence_no
        text line_text
    }

    llm_endpoints {
        uuid endpoint_uuid PK
        text endpoint_alias UK
        text base_url
        boolean active
    }

    llm_endpoint_models {
        uuid endpoint_uuid PK,FK
        text model_id PK
        text tokenizer_model
    }

    llm_remote_batch_jobs {
        uuid remote_job_uuid PK
        text tenant_scope
        text endpoint_alias
        text remote_batch_id
        bigint observation_order
        text batch_status
    }

    llm_result_stream_checkpoints {
        uuid result_checkpoint_uuid PK
        text tenant_scope
        text checkpoint_consumer_name
        text endpoint_alias
        text remote_batch_id
        text prefix_sha256
    }

    llm_queues ||--o{ llm_batches : contains
    llm_queues ||--o{ llm_batch_files : owns
    llm_batches ||--o{ llm_batch_files : partitions
    llm_batch_file_payloads ||--o{ llm_batch_files : stores
    llm_batches ||--o{ llm_requests : queues
    llm_batch_files ||--o{ llm_requests : assigns
    llm_batch_file_payloads ||--o{ llm_jsonl_lines : lines
    llm_requests ||--o{ llm_jsonl_lines : reconstructs
    llm_endpoints ||--o{ llm_endpoint_models : maps
```

`llm_remote_batch_jobs` and `llm_result_stream_checkpoints` are intentionally
unrelated to the preparation graph. Their tenant-qualified unique keys are the
lifecycle and checkpoint identities. Migration 0007 owns the checkpoint table;
the packaged `schema.sql` / Docker init mirror do not create it.

## Third-normal-form boundary

Preparation tables keep queue, batch, payload, request, and line facts in
separate relations with explicit keys. Endpoint/model mapping is a separate
relation from lifecycle projection. The KV tables `com_config` and `com_secrets`
are key/value stores by design: each row is one setting, not a repeating group
inside another entity. Do not add single-word table names or embed tenant
authority in provider columns.
