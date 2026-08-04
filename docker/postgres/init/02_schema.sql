-- SPDX-License-Identifier: Apache-2.0
-- Build-context mirror of pg_llm_batch/schema.sql (canonical source read by
-- pg_llm_batch/db.py). Kept here so docker/postgres/Dockerfile builds with its
-- own directory as the build context (the central coverage-evidence job builds
-- each changed Dockerfile with context = its own directory). Keep in sync with
-- pg_llm_batch/schema.sql.
-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) ContextualWisdomLab.
-- pg-llm-batch: batch DDL subset extracted from xtrmLLMBatchPython.
-- All object names are 2+ word snake_case per the org DB naming rule.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Some deployments provide uuid_generate_v4 via uuid-ossp; fall back to
-- pgcrypto's gen_random_uuid() when the extension is unavailable.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'uuid_generate_v4') THEN
        CREATE OR REPLACE FUNCTION uuid_generate_v4() RETURNS uuid
            LANGUAGE sql AS 'SELECT gen_random_uuid()';
    END IF;
END $$;

-- =============================================================================
-- KV configuration + secrets (replace os.getenv)
-- =============================================================================
CREATE TABLE IF NOT EXISTS com_config (
    config_key TEXT PRIMARY KEY,
    config_value TEXT NOT NULL,
    config_description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS com_secrets (
    secret_key TEXT PRIMARY KEY,
    secret_value TEXT NOT NULL,
    is_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Queues and batches
-- =============================================================================
CREATE TABLE IF NOT EXISTS llm_queues (
    queue_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    queue_name TEXT UNIQUE NOT NULL,
    queue_status TEXT NOT NULL DEFAULT 'active'
        CHECK (queue_status IN ('active', 'paused', 'stopped')),
    queue_description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_batches (
    batch_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    queue_uuid UUID NOT NULL REFERENCES llm_queues(queue_uuid) ON DELETE CASCADE,
    batch_name TEXT NOT NULL,
    batch_status TEXT NOT NULL DEFAULT 'queued'
        CHECK (batch_status IN ('queued', 'validating', 'in_progress',
                                'finalizing', 'processing', 'completed',
                                'failed', 'cancelled')),
    model_name TEXT NOT NULL,
    total_requests INTEGER NOT NULL DEFAULT 0,
    completed_requests INTEGER NOT NULL DEFAULT 0,
    failed_requests INTEGER NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    max_tokens_per_batch BIGINT NOT NULL DEFAULT 5000000000,
    input_file_path TEXT,
    output_file_path TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL
);

-- Database-owned ordering is reserved before remote provider I/O. Sequence
-- values are intentionally not transactional, so failed requests leave harmless
-- gaps rather than allowing a later request to reuse an older order.
CREATE SEQUENCE IF NOT EXISTS llm_remote_batch_observation_sequence
    AS BIGINT
    INCREMENT BY 1
    MINVALUE 1
    START WITH 1
    NO CYCLE;

-- Curated, provider-facing lifecycle state. The compound identity makes repeated
-- polling idempotent without assuming remote identifiers are globally unique.
CREATE TABLE IF NOT EXISTS llm_remote_batch_jobs (
    remote_job_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    endpoint_alias TEXT NOT NULL
        CHECK (LENGTH(endpoint_alias) BETWEEN 1 AND 128),
    remote_batch_id TEXT NOT NULL
        CHECK (LENGTH(remote_batch_id) BETWEEN 1 AND 256)
        CHECK (remote_batch_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'),
    observation_order BIGINT NOT NULL
        CHECK (observation_order > 0),
    input_file_id TEXT
        CHECK (
            input_file_id IS NULL OR
            input_file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
        ),
    batch_endpoint TEXT,
    batch_status TEXT NOT NULL,
    output_file_id TEXT
        CHECK (
            output_file_id IS NULL OR
            output_file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
        ),
    error_file_id TEXT
        CHECK (
            error_file_id IS NULL OR
            error_file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
        ),
    total_requests INTEGER NOT NULL DEFAULT 0
        CHECK (total_requests >= 0),
    completed_requests INTEGER NOT NULL DEFAULT 0
        CHECK (completed_requests >= 0),
    failed_requests INTEGER NOT NULL DEFAULT 0
        CHECK (failed_requests >= 0),
    provider_metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_observed_at TIMESTAMPTZ NOT NULL,
    terminal_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_llm_remote_batch_jobs_endpoint_id
        UNIQUE (endpoint_alias, remote_batch_id)
);

CREATE INDEX IF NOT EXISTS idx_llm_remote_batch_jobs_status_observed
    ON llm_remote_batch_jobs(batch_status, last_observed_at);

CREATE TABLE IF NOT EXISTS llm_batch_file_payloads (
    file_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_id TEXT UNIQUE NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_batch_files (
    file_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_uuid UUID NOT NULL REFERENCES llm_batches(batch_uuid) ON DELETE CASCADE,
    queue_uuid UUID NOT NULL,
    file_path TEXT NOT NULL,
    payload_file_id TEXT REFERENCES llm_batch_file_payloads(file_id),
    storage_ref TEXT,
    part_index INTEGER NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uploaded_at TIMESTAMPTZ NULL,
    CONSTRAINT fk_llm_batch_files_queue
        FOREIGN KEY (queue_uuid)
        REFERENCES llm_queues(queue_uuid) ON DELETE CASCADE
);

-- Migrate legacy installations where queue_uuid had an unrelated random default
-- and no foreign key. Do not delete or silently re-parent orphaned data.
ALTER TABLE llm_batch_files ALTER COLUMN queue_uuid DROP DEFAULT;
DO $$
DECLARE
    orphan_count BIGINT;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_llm_batch_files_queue'
          AND conrelid = 'llm_batch_files'::regclass
    ) THEN
        SELECT COUNT(*)
        INTO orphan_count
        FROM llm_batch_files AS batch_file
        LEFT JOIN llm_queues AS queue_row
          ON queue_row.queue_uuid = batch_file.queue_uuid
        WHERE queue_row.queue_uuid IS NULL;

        IF orphan_count > 0 THEN
            RAISE EXCEPTION
                'Cannot add fk_llm_batch_files_queue: % orphaned llm_batch_files rows',
                orphan_count
                USING ERRCODE = '23503';
        END IF;

        ALTER TABLE llm_batch_files
            ADD CONSTRAINT fk_llm_batch_files_queue
            FOREIGN KEY (queue_uuid)
            REFERENCES llm_queues(queue_uuid) ON DELETE CASCADE;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS llm_requests (
    request_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_uuid UUID NOT NULL REFERENCES llm_batches(batch_uuid) ON DELETE CASCADE,
    custom_request_id TEXT,
    system_prompt TEXT NOT NULL DEFAULT '',
    user_prompt TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    request_status TEXT NOT NULL DEFAULT 'queued'
        CHECK (request_status IN ('queued', 'processing', 'completed',
                                  'failed', 'retrying')),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    response_content TEXT,
    response_metadata JSONB,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    batch_file_uuid UUID REFERENCES llm_batch_files(file_uuid)
);

CREATE TABLE IF NOT EXISTS llm_jsonl_lines (
    line_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    payload_file_id TEXT NOT NULL
        REFERENCES llm_batch_file_payloads(file_id) ON DELETE CASCADE,
    request_uuid UUID NOT NULL
        REFERENCES llm_requests(request_uuid) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    line_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Stable identities used by preparation, replay, and JOIN-only reconstruction.
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_batches_input_file_path
    ON llm_batches(input_file_path)
    WHERE input_file_path IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_batch_files_batch_part
    ON llm_batch_files(batch_uuid, part_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_batch_files_file_path
    ON llm_batch_files(file_path);
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_batch_files_payload_file
    ON llm_batch_files(payload_file_id)
    WHERE payload_file_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_jsonl_lines_payload_request
    ON llm_jsonl_lines(payload_file_id, request_uuid);
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_jsonl_lines_payload_sequence
    ON llm_jsonl_lines(payload_file_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_llm_jsonl_lines_req
    ON llm_jsonl_lines(request_uuid);

-- Preparation scans only queued, unassigned requests for one batch.
CREATE INDEX IF NOT EXISTS idx_llm_requests_batch_prepare
    ON llm_requests(batch_uuid, created_at)
    WHERE request_status = 'queued' AND batch_file_uuid IS NULL;
CREATE INDEX IF NOT EXISTS idx_llm_batches_status_updated
    ON llm_batches(batch_status, updated_at);

-- Superseded by the unique (payload, sequence) index above.
DROP INDEX IF EXISTS idx_llm_jsonl_lines_payload;

-- =============================================================================
-- Endpoint <-> model <-> tokenizer mapping (populated by the pg_cron sync job)
-- =============================================================================
CREATE TABLE IF NOT EXISTS llm_endpoints (
    endpoint_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    endpoint_alias TEXT UNIQUE NOT NULL,
    base_url TEXT NOT NULL,
    provider TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_endpoint_models (
    endpoint_uuid UUID NOT NULL
        REFERENCES llm_endpoints(endpoint_uuid) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    tokenizer_model TEXT,
    model_mode TEXT,
    last_verified_at TIMESTAMPTZ,
    PRIMARY KEY (endpoint_uuid, model_id)
);

-- =============================================================================
-- Readiness probe helper (used by /healthz and `count-tokens --self-check`)
-- =============================================================================
CREATE OR REPLACE FUNCTION pg_llm_batch_health_check()
RETURNS TABLE(component TEXT, is_ready BOOLEAN, detail TEXT) AS $$
BEGIN
    RETURN QUERY SELECT 'database'::TEXT, TRUE, 'reachable'::TEXT;

    RETURN QUERY SELECT 'pg_tiktoken'::TEXT,
        EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_tiktoken'),
        COALESCE((SELECT extversion FROM pg_extension
                  WHERE extname = 'pg_tiktoken'), 'not installed');

    RETURN QUERY SELECT 'pg_cron'::TEXT,
        EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron'),
        COALESCE((SELECT extversion FROM pg_extension
                  WHERE extname = 'pg_cron'), 'not installed');

    RETURN QUERY SELECT 'http'::TEXT,
        EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'http'),
        COALESCE((SELECT extversion FROM pg_extension
                  WHERE extname = 'http'), 'not installed');

    RETURN QUERY SELECT 'com_config'::TEXT,
        EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_name = 'com_config'),
        'kv config store'::TEXT;
END;
$$ LANGUAGE plpgsql;
