-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) ContextualWisdomLab.
-- Durable tenant-isolated result checkpoints with compare-and-swap writers.

DO $$
BEGIN
    CREATE TABLE IF NOT EXISTS llm_result_stream_checkpoints (
        result_checkpoint_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_scope TEXT NOT NULL DEFAULT 'standalone',
        checkpoint_consumer_name TEXT NOT NULL,
        endpoint_alias TEXT NOT NULL,
        remote_batch_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        file_kind TEXT NOT NULL,
        file_id TEXT NOT NULL,
        file_line_number BIGINT NOT NULL,
        batch_line_count BIGINT NOT NULL,
        record_count BIGINT NOT NULL,
        prefix_sha256 TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_llm_result_stream_checkpoints_tenant_scope
            CHECK (tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
        CONSTRAINT ck_llm_result_stream_checkpoints_consumer_name
            CHECK (
                checkpoint_consumer_name ~
                '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            ),
        CONSTRAINT ck_llm_result_stream_checkpoints_endpoint_alias
            CHECK (LENGTH(endpoint_alias) BETWEEN 1 AND 128),
        CONSTRAINT ck_llm_result_stream_checkpoints_remote_batch_id
            CHECK (remote_batch_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'),
        CONSTRAINT ck_llm_result_stream_checkpoints_schema_version
            CHECK (schema_version = 1),
        CONSTRAINT ck_llm_result_stream_checkpoints_file_kind
            CHECK (file_kind IN ('result', 'error')),
        CONSTRAINT ck_llm_result_stream_checkpoints_file_id
            CHECK (file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'),
        CONSTRAINT ck_llm_result_stream_checkpoints_line_counts
            CHECK (
                file_line_number > 0 AND
                batch_line_count >= file_line_number AND
                record_count > 0 AND
                record_count <= batch_line_count
            ),
        CONSTRAINT ck_llm_result_stream_checkpoints_prefix_sha256
            CHECK (prefix_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT uq_llm_result_stream_checkpoints_tenant_consumer_batch
            UNIQUE (
                tenant_scope,
                checkpoint_consumer_name,
                endpoint_alias,
                remote_batch_id
            )
    );

    ALTER TABLE llm_result_stream_checkpoints ENABLE ROW LEVEL SECURITY;
    ALTER TABLE llm_result_stream_checkpoints FORCE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS plc_llm_result_stream_checkpoints_tenant_scope
        ON llm_result_stream_checkpoints;
    CREATE POLICY plc_llm_result_stream_checkpoints_tenant_scope
        ON llm_result_stream_checkpoints
        TO PUBLIC
        USING (
            tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
        )
        WITH CHECK (
            tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
        );

    CREATE INDEX IF NOT EXISTS idx_llm_result_stream_checkpoints_tenant_updated
        ON llm_result_stream_checkpoints(
            tenant_scope,
            updated_at
        );
END $$;
