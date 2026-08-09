-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) ContextualWisdomLab.
-- Append-only tenant-isolated evidence for accepted checkpoint save calls.

CREATE TABLE IF NOT EXISTS llm_result_checkpoint_audit_events (
    checkpoint_audit_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_scope TEXT NOT NULL DEFAULT 'standalone',
    checkpoint_consumer_name TEXT NOT NULL,
    endpoint_alias TEXT NOT NULL,
    remote_batch_id TEXT NOT NULL,
    event_action TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    file_kind TEXT NOT NULL,
    file_id TEXT NOT NULL,
    file_line_number BIGINT NOT NULL,
    batch_line_count BIGINT NOT NULL,
    record_count BIGINT NOT NULL,
    prefix_sha256 TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_tenant_scope
        CHECK (tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_consumer_name
        CHECK (
            checkpoint_consumer_name ~
            '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
        ),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_endpoint_alias
        CHECK (LENGTH(endpoint_alias) BETWEEN 1 AND 128),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_remote_batch_id
        CHECK (remote_batch_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_action
        CHECK (event_action = 'checkpoint_save_accepted'),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_schema_version
        CHECK (schema_version = 1),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_file_kind
        CHECK (file_kind IN ('result', 'error')),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_file_id
        CHECK (file_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_line_counts
        CHECK (
            file_line_number > 0 AND
            batch_line_count >= file_line_number AND
            record_count > 0 AND
            record_count <= batch_line_count
        ),
    CONSTRAINT ck_llm_result_checkpoint_audit_events_prefix_sha256
        CHECK (prefix_sha256 ~ '^[0-9a-f]{64}$')
);

-- NOW()/CURRENT_TIMESTAMP are fixed at transaction start in PostgreSQL. Repair
-- prior development applications of this idempotent migration and ensure each
-- accepted-save row records wall-clock time at the insert itself.
ALTER TABLE llm_result_checkpoint_audit_events
    ALTER COLUMN recorded_at SET DEFAULT clock_timestamp();

ALTER TABLE llm_result_checkpoint_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_result_checkpoint_audit_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS plc_llm_result_checkpoint_audit_events_tenant_scope
    ON llm_result_checkpoint_audit_events;
CREATE POLICY plc_llm_result_checkpoint_audit_events_tenant_scope
    ON llm_result_checkpoint_audit_events
    TO PUBLIC
    USING (
        tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
    )
    WITH CHECK (
        tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
    );

CREATE INDEX IF NOT EXISTS idx_llm_result_checkpoint_audit_events_tenant_recorded
    ON llm_result_checkpoint_audit_events(
        tenant_scope,
        recorded_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_llm_result_checkpoint_audit_events_checkpoint_key
    ON llm_result_checkpoint_audit_events(
        tenant_scope,
        checkpoint_consumer_name,
        endpoint_alias,
        remote_batch_id,
        checkpoint_audit_event_id DESC
    );

DROP TRIGGER IF EXISTS checkpoint_audit_row_immutability
    ON llm_result_checkpoint_audit_events;
DROP TRIGGER IF EXISTS checkpoint_audit_truncate_immutability
    ON llm_result_checkpoint_audit_events;
DROP FUNCTION IF EXISTS reject_checkpoint_audit_mutation();

CREATE FUNCTION reject_checkpoint_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'checkpoint audit evidence is append-only'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER checkpoint_audit_row_immutability
    BEFORE UPDATE OR DELETE
    ON llm_result_checkpoint_audit_events
    FOR EACH ROW
    EXECUTE FUNCTION reject_checkpoint_audit_mutation();

CREATE TRIGGER checkpoint_audit_truncate_immutability
    BEFORE TRUNCATE
    ON llm_result_checkpoint_audit_events
    FOR EACH STATEMENT
    EXECUTE FUNCTION reject_checkpoint_audit_mutation();
