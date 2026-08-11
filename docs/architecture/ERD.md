# Logical data model / ERD

## Authority

The protected-main schema in `pg_llm_batch/schema.sql` is the authority for **IMPLEMENTED-ON-PROTECTED-MAIN** persistence. Open pull requests may add tables or constraints; those are shown only as **ACTIVE-PR** overlays. This document does not invent persistence to satisfy diagram coverage.

## Protected-main persisted model

```mermaid
erDiagram
    com_config {
        text config_key PK
        text config_value
        text config_description
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
        timestamptz updated_at
    }
    llm_batches {
        uuid batch_uuid PK
        uuid queue_uuid FK
        text batch_name
        text batch_status
        text model_name
        bigint total_tokens
    }
    llm_batch_file_payloads {
        uuid file_uuid PK
        text file_id UK
        jsonb content
    }
    llm_batch_files {
        uuid file_uuid PK
        uuid batch_uuid FK
        uuid queue_uuid FK
        text payload_file_id FK
        integer part_index
    }
    llm_requests {
        uuid request_uuid PK
        uuid batch_uuid FK
        uuid batch_file_uuid FK
        text request_status
        text model_name
    }
    llm_jsonl_lines {
        uuid line_uuid PK
        text payload_file_id FK
        uuid request_uuid FK
        integer sequence_no
    }
    llm_endpoints {
        uuid endpoint_uuid PK
        text endpoint_alias UK
        text base_url
        text provider
        boolean active
    }
    llm_endpoint_models {
        uuid endpoint_uuid FK
        text model_id PK
        text tokenizer_model
        text model_mode
    }
    llm_remote_batch_jobs {
        uuid remote_job_uuid PK
        text endpoint_alias
        text remote_batch_id
        bigint observation_order
        text input_file_id
        text batch_endpoint
        text batch_status
        text output_file_id
        text error_file_id
        bigint total_requests
        bigint completed_requests
        bigint failed_requests
        jsonb provider_metadata
        timestamptz first_seen_at
        timestamptz last_observed_at
        timestamptz terminal_at
        timestamptz updated_at
    }

    llm_queues ||--o{ llm_batches : contains
    llm_queues ||--o{ llm_batch_files : scopes
    llm_batches ||--o{ llm_batch_files : partitions
    llm_batches ||--o{ llm_requests : contains
    llm_batch_files o|--o{ llm_requests : assigns
    llm_batch_file_payloads ||--o{ llm_batch_files : materializes
    llm_batch_file_payloads ||--o{ llm_jsonl_lines : contains
    llm_requests ||--o{ llm_jsonl_lines : serializes
    llm_endpoints ||--o{ llm_endpoint_models : advertises
```

All entities above are **IMPLEMENTED-ON-PROTECTED-MAIN** at the documentation baseline. `llm_remote_batch_jobs` uses composite UNIQUE `(endpoint_alias, remote_batch_id)` as the durable provider-facing identity and idempotency key on protected main; `remote_job_uuid` remains its row primary key. ACTIVE-PR #53 introduces trusted tenant qualification and forced RLS for the remote lifecycle projection; that tenant boundary is not claimed here as shipped.

The protected-main content-bearing work tables `llm_queues`, `llm_batches`, `llm_batch_files`, `llm_batch_file_payloads`, `llm_requests`, and `llm_jsonl_lines` are **not tenant-qualified**. ACTIVE-PR #53 is a **remote lifecycle** isolation slice and does not retrofit those core tables. Issue #130 is the PLANNED follow-up for tenant-scoped content-bearing work state after the protected #53 and #87 results can be composed safely. This ERD therefore does not imply end-to-end tenant isolation and does not invent `tenant_scope` columns, keys, policies, or relationships that do not yet exist.

## ACTIVE-PR persistence overlay

The following persistence exists in open implementation branches and remains **ACTIVE-PR** until integrated:

- `llm_result_stream_checkpoints` — introduced by #60; tenant-qualified durable checkpoint CAS state with forced RLS.
- `llm_result_checkpoint_audit_events` — carried by the current audit replacement #94; append-only accepted-save evidence with forced RLS and immutability triggers.

```mermaid
erDiagram
    llm_result_stream_checkpoints {
        uuid result_checkpoint_uuid PK
        text tenant_scope
        text checkpoint_consumer_name
        text endpoint_alias
        text remote_batch_id
        integer schema_version
        text file_kind
        text file_id
        bigint file_line_number
        bigint batch_line_count
        bigint record_count
        text prefix_sha256
        timestamptz created_at
        timestamptz updated_at
    }
    llm_result_checkpoint_audit_events {
        bigint checkpoint_audit_event_id PK
        text tenant_scope
        text checkpoint_consumer_name
        text endpoint_alias
        text remote_batch_id
        text event_action
        integer schema_version
        text file_kind
        text file_id
        bigint file_line_number
        bigint batch_line_count
        bigint record_count
        text prefix_sha256
        timestamptz recorded_at
    }

    llm_result_stream_checkpoints ||--o{ llm_result_checkpoint_audit_events : accepted_save_evidence
```

The relationship is logical: the audit event copies the accepted checkpoint identity/evidence. The current migration does not declare a foreign key between the two tables, so the ERD intentionally does not imply database-enforced referential integrity.

## Ownership and non-persistence boundaries

Provider credentials are represented in `com_config`/`com_secrets` according to the current package contract, but external provider objects, HTTP responses, model inventories, GitHub review evidence, and scheduler state are not application tables in this schema. GitHub checks/reviews/workflow runs are operational evidence, not rows in pg-llm-batch's product database. CWL sibling services remain separate bounded contexts and must not gain hidden direct access to these tables through this documentation.

## Migration discipline

Schema changes must have explicit forward and rollback/recovery treatment, deterministic tests, protected-main/ACTIVE-PR maturity labeling, and updated traceability. A migration present only in an open PR remains **ACTIVE-PR** even if its SQL has passed branch-local integration tests.
