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
    queue_uuid UUID NOT NULL DEFAULT uuid_generate_v4(),
    file_path TEXT NOT NULL,
    payload_file_id TEXT REFERENCES llm_batch_file_payloads(file_id),
    storage_ref TEXT,
    part_index INTEGER NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uploaded_at TIMESTAMPTZ NULL
);

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
CREATE INDEX IF NOT EXISTS idx_llm_jsonl_lines_payload
    ON llm_jsonl_lines(payload_file_id);
CREATE INDEX IF NOT EXISTS idx_llm_jsonl_lines_req
    ON llm_jsonl_lines(request_uuid);

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
