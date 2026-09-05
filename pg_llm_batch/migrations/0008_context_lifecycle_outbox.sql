-- SPDX-License-Identifier: Apache-2.0
-- Durable, privacy-minimized lifecycle publication intent owned by pg-llm-batch.

DO $$
BEGIN
    -- Bind name resolution before any DDL/catalog lookup. Explicit pg_temp placement
    -- prevents temporary relations from being searched ahead of the reviewed schema.
    PERFORM pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true);

    CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox (
        context_outbox_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        tenant_scope TEXT NOT NULL DEFAULT 'standalone',
        evidence_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        tenant_scope_sha256 TEXT NOT NULL,
        subject_ref_sha256 TEXT NOT NULL,
        authority_ref_sha256 TEXT NOT NULL,
        origin_ref_sha256 TEXT NOT NULL,
        truth_status TEXT NOT NULL,
        valid_time TEXT NOT NULL,
        system_time TEXT NOT NULL,
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

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            ADD CONSTRAINT ck_llm_context_lifecycle_outbox_valid_time_canonical_v1
            CHECK (
                valid_time ~
                '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([.]\d{6})?Z$'
                AND valid_time::timestamptz IS NOT NULL
                AND valid_time !~ '[.]000000Z$'
                AND valid_time = CASE
                    WHEN valid_time ~ '[.]' THEN
                        to_char(
                            valid_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                        )
                    ELSE
                        to_char(
                            valid_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                        )
                END
            );
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_valid_time'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_valid_time;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_system_time_canonical_v1'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            ADD CONSTRAINT ck_llm_context_lifecycle_outbox_system_time_canonical_v1
            CHECK (
                system_time ~
                '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([.]\d{6})?Z$'
                AND system_time::timestamptz IS NOT NULL
                AND system_time !~ '[.]000000Z$'
                AND system_time = CASE
                    WHEN system_time ~ '[.]' THEN
                        to_char(
                            system_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                        )
                    ELSE
                        to_char(
                            system_time::timestamptz AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                        )
                END
            );
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_system_time'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_system_time;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE oid = 'llm_context_lifecycle_outbox'::regclass
          AND relrowsecurity
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox ENABLE ROW LEVEL SECURITY;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE oid = 'llm_context_lifecycle_outbox'::regclass
          AND relforcerowsecurity
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox FORCE ROW LEVEL SECURITY;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_policy
        WHERE polrelid = 'llm_context_lifecycle_outbox'::regclass
          AND polname NOT IN (
              'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2',
              'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v1',
              'plc_llm_context_lifecycle_outbox_tenant_scope'
          )
    ) THEN
        RAISE EXCEPTION 'unexpected lifecycle outbox row-security policy';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policy
        WHERE polrelid = 'llm_context_lifecycle_outbox'::regclass
          AND polname = 'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2'
          AND polcmd = '*'
          AND polpermissive
          AND polroles = ARRAY[0::oid]
          AND pg_catalog.pg_get_expr(polqual, polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND pg_catalog.pg_get_expr(polwithcheck, polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM pg_policy
            WHERE polrelid = 'llm_context_lifecycle_outbox'::regclass
              AND polname = 'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2'
        ) THEN
            DROP POLICY plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2
                ON llm_context_lifecycle_outbox;
        END IF;

        CREATE POLICY plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2
            ON llm_context_lifecycle_outbox
            TO PUBLIC
            USING (
                tenant_scope OPERATOR(pg_catalog.=)
                    pg_catalog.current_setting('pg_llm_batch.tenant_scope', true)
            )
            WITH CHECK (
                tenant_scope OPERATOR(pg_catalog.=)
                    pg_catalog.current_setting('pg_llm_batch.tenant_scope', true)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policy
        WHERE polrelid = 'llm_context_lifecycle_outbox'::regclass
          AND polname = 'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2'
          AND polcmd = '*'
          AND polpermissive
          AND polroles = ARRAY[0::oid]
          AND pg_catalog.pg_get_expr(polqual, polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND pg_catalog.pg_get_expr(polwithcheck, polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox row-security policy failed canonical verification';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_policy
        WHERE polrelid = 'llm_context_lifecycle_outbox'::regclass
          AND polname = 'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v1'
    ) THEN
        DROP POLICY plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v1
            ON llm_context_lifecycle_outbox;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_policy
        WHERE polrelid = 'llm_context_lifecycle_outbox'::regclass
          AND polname = 'plc_llm_context_lifecycle_outbox_tenant_scope'
    ) THEN
        DROP POLICY plc_llm_context_lifecycle_outbox_tenant_scope
            ON llm_context_lifecycle_outbox;
    END IF;

    CREATE INDEX IF NOT EXISTS idx_llm_context_lifecycle_outbox_tenant_created
        ON llm_context_lifecycle_outbox(tenant_scope, created_at);
END $$;
