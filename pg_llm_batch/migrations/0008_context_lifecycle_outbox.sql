-- SPDX-License-Identifier: Apache-2.0
-- Durable, privacy-minimized lifecycle publication intent owned by pg-llm-batch.

DO $$
BEGIN
    CREATE TABLE IF NOT EXISTS llm_context_lifecycle_outbox (
        context_outbox_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_scope TEXT NOT NULL DEFAULT 'standalone',
        evidence_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        tenant_scope_sha256 TEXT NOT NULL,
        subject_ref_sha256 TEXT NOT NULL,
        authority_ref_sha256 TEXT NOT NULL,
        origin_ref_sha256 TEXT NOT NULL,
        truth_status TEXT NOT NULL,
        valid_time TIMESTAMPTZ NOT NULL,
        system_time TIMESTAMPTZ NOT NULL,
        provenance_ref_sha256 TEXT NOT NULL,
        evidence_ref_sha256 TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_llm_context_lifecycle_outbox_tenant_scope
            CHECK (tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_evidence_id
            CHECK (evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_event_type
            CHECK (event_type ~ '^[a-z][a-z0-9._:-]{0,127}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_tenant_sha256
            CHECK (tenant_scope_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_subject_sha256
            CHECK (subject_ref_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_authority_sha256
            CHECK (authority_ref_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_origin_sha256
            CHECK (origin_ref_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_truth_status
            CHECK (
                truth_status IN (
                    'authoritative',
                    'observed',
                    'inferred',
                    'proposed',
                    'superseded',
                    'rejected'
                )
            ),
        CONSTRAINT ck_llm_context_lifecycle_outbox_provenance_sha256
            CHECK (provenance_ref_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_llm_context_lifecycle_outbox_evidence_sha256
            CHECK (evidence_ref_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT uq_llm_context_lifecycle_outbox_tenant_evidence
            UNIQUE (tenant_scope, evidence_id)
    );

    ALTER TABLE llm_context_lifecycle_outbox ENABLE ROW LEVEL SECURITY;
    ALTER TABLE llm_context_lifecycle_outbox FORCE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS plc_llm_context_lifecycle_outbox_tenant_scope
        ON llm_context_lifecycle_outbox;
    CREATE POLICY plc_llm_context_lifecycle_outbox_tenant_scope
        ON llm_context_lifecycle_outbox
        TO PUBLIC
        USING (
            tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
        )
        WITH CHECK (
            tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
        );

    CREATE INDEX IF NOT EXISTS idx_llm_context_lifecycle_outbox_tenant_created
        ON llm_context_lifecycle_outbox(tenant_scope, created_at);
END $$;
