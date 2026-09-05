-- SPDX-License-Identifier: Apache-2.0
-- Durable, privacy-minimized lifecycle publication intent owned by pg-llm-batch.

DO $$
DECLARE
    canonical_payload_check_expression TEXT;
    canonical_valid_time_check_expression TEXT;
    canonical_system_time_check_expression TEXT;
BEGIN
    -- Bind name resolution before any DDL/catalog lookup. Explicit pg_temp placement
    -- prevents temporary relations from being searched ahead of the reviewed schema.
    PERFORM pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true);

    CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox (
        context_outbox_uuid UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
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
        FROM pg_class AS outbox_relation
        JOIN pg_namespace AS outbox_namespace
          ON outbox_namespace.oid = outbox_relation.relnamespace
        WHERE outbox_relation.oid = 'public.llm_context_lifecycle_outbox'::regclass
          AND outbox_relation.relkind = 'r'
          AND outbox_relation.relpersistence = 'p'
          AND outbox_namespace.nspname = 'public'
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_inherits AS inheritance_edge
        WHERE inheritance_edge.inhrelid =
              'public.llm_context_lifecycle_outbox'::regclass
           OR inheritance_edge.inhparent =
              'public.llm_context_lifecycle_outbox'::regclass
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_trigger AS outbox_trigger
        WHERE outbox_trigger.tgrelid =
              'public.llm_context_lifecycle_outbox'::regclass
          AND NOT outbox_trigger.tgisinternal
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_rewrite AS outbox_rule
        WHERE outbox_rule.ev_class =
              'public.llm_context_lifecycle_outbox'::regclass
    ) OR EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('context_outbox_uuid', 'uuid'::regtype, true, true),
                ('tenant_scope', 'text'::regtype, true, true),
                ('evidence_id', 'text'::regtype, true, false),
                ('event_type', 'text'::regtype, true, false),
                ('tenant_scope_sha256', 'text'::regtype, true, false),
                ('subject_ref_sha256', 'text'::regtype, true, false),
                ('authority_ref_sha256', 'text'::regtype, true, false),
                ('origin_ref_sha256', 'text'::regtype, true, false),
                ('truth_status', 'text'::regtype, true, false),
                ('valid_time', 'text'::regtype, true, false),
                ('system_time', 'text'::regtype, true, false),
                ('provenance_ref_sha256', 'text'::regtype, true, false),
                ('evidence_ref_sha256', 'text'::regtype, true, false),
                ('created_at', 'timestamptz'::regtype, true, true)
        ) AS expected(attname, atttypid, attnotnull, atthasdef)
        LEFT JOIN pg_attribute AS actual
          ON actual.attrelid = 'llm_context_lifecycle_outbox'::regclass
         AND actual.attname = expected.attname
         AND actual.attnum > 0
         AND NOT actual.attisdropped
        WHERE actual.attnum IS NULL
           OR actual.atttypid IS DISTINCT FROM expected.atttypid
           OR actual.attcollation IS DISTINCT FROM (
               SELECT typcollation
               FROM pg_type
               WHERE oid = expected.atttypid
           )
           OR actual.attnotnull IS DISTINCT FROM expected.attnotnull
           OR actual.atthasdef IS DISTINCT FROM expected.atthasdef
           OR actual.attgenerated <> ''
           OR actual.attidentity <> ''
    ) OR (
        SELECT count(*)
        FROM pg_attribute AS actual
        WHERE actual.attrelid = 'llm_context_lifecycle_outbox'::regclass
          AND actual.attnum > 0
          AND NOT actual.attisdropped
    ) <> 14 OR EXISTS (
        SELECT 1
        FROM pg_attribute AS dropped_column
        WHERE dropped_column.attrelid = 'llm_context_lifecycle_outbox'::regclass
          AND dropped_column.attnum > 0
          AND dropped_column.attisdropped
    ) OR EXISTS (
        SELECT 1
        FROM pg_attribute AS actual
        JOIN pg_attrdef AS defaults
          ON defaults.adrelid = actual.attrelid
         AND defaults.adnum = actual.attnum
        WHERE actual.attrelid = 'llm_context_lifecycle_outbox'::regclass
          AND NOT actual.attisdropped
          AND (
              (
                  actual.attname = 'tenant_scope'
                  AND pg_catalog.pg_get_expr(
                      defaults.adbin,
                      defaults.adrelid,
                      false
                  ) <> '''standalone''::text'
              )
              OR (
                  actual.attname = 'created_at'
                  AND pg_catalog.pg_get_expr(
                      defaults.adbin,
                      defaults.adrelid,
                      false
                  ) <> 'now()'
              )
          )
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND contype = 'p'
          AND convalidated
          AND NOT condeferrable
          AND conkey = ARRAY[
              (SELECT attnum::smallint
               FROM pg_attribute
               WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                 AND attname = 'context_outbox_uuid'
                 AND NOT attisdropped)
          ]
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox structural schema mismatch';
    END IF;

    -- UUID generation is durable identity authority. Converge any predecessor or
    -- restored default to PostgreSQL's core v4 generator without rewriting rows.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_attribute AS actual
        JOIN pg_attrdef AS defaults
          ON defaults.adrelid = actual.attrelid
         AND defaults.adnum = actual.attnum
        WHERE actual.attrelid = 'llm_context_lifecycle_outbox'::regclass
          AND actual.attname = 'context_outbox_uuid'
          AND actual.attnum > 0
          AND NOT actual.attisdropped
          AND pg_catalog.pg_get_expr(
              defaults.adbin,
              defaults.adrelid,
              false
          ) = 'gen_random_uuid()'
    ) THEN
        ALTER TABLE public.llm_context_lifecycle_outbox
            ALTER COLUMN context_outbox_uuid SET DEFAULT pg_catalog.gen_random_uuid();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_attribute AS actual
        JOIN pg_attrdef AS defaults
          ON defaults.adrelid = actual.attrelid
         AND defaults.adnum = actual.attnum
        WHERE actual.attrelid = 'llm_context_lifecycle_outbox'::regclass
          AND actual.attname = 'context_outbox_uuid'
          AND actual.attnum > 0
          AND NOT actual.attisdropped
          AND pg_catalog.pg_get_expr(
              defaults.adbin,
              defaults.adrelid,
              false
          ) = 'gen_random_uuid()'
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox UUID default failed canonical verification';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'uq_llm_context_lifecycle_outbox_tenant_evidence'
          AND contype = 'u'
          AND convalidated
          AND NOT condeferrable
          AND conkey = ARRAY[
              (SELECT attnum::smallint FROM pg_attribute
               WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                 AND attname = 'tenant_scope' AND NOT attisdropped),
              (SELECT attnum::smallint FROM pg_attribute
               WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                 AND attname = 'evidence_id' AND NOT attisdropped)
          ]
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
              AND conname = 'uq_llm_context_lifecycle_outbox_tenant_evidence'
        ) THEN
            ALTER TABLE llm_context_lifecycle_outbox
                DROP CONSTRAINT uq_llm_context_lifecycle_outbox_tenant_evidence;
        END IF;

        ALTER TABLE llm_context_lifecycle_outbox
            ADD CONSTRAINT uq_llm_context_lifecycle_outbox_tenant_evidence
            UNIQUE (tenant_scope, evidence_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'uq_llm_context_lifecycle_outbox_tenant_evidence'
          AND contype = 'u'
          AND convalidated
          AND NOT condeferrable
          AND conkey = ARRAY[
              (SELECT attnum::smallint FROM pg_attribute
               WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                 AND attname = 'tenant_scope' AND NOT attisdropped),
              (SELECT attnum::smallint FROM pg_attribute
               WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                 AND attname = 'evidence_id' AND NOT attisdropped)
          ]
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox replay arbiter failed canonical verification';
    END IF;

    -- Derive canonical CHECK parser output from this PostgreSQL runtime instead of
    -- trusting mutable COMMENT metadata or hard-coding version-sensitive deparser text.
    -- The probe is session-local, never touches durable rows, and is explicitly removed
    -- before production constraint admission.
    CREATE TEMPORARY TABLE pg_llm_batch_outbox_constraint_probe_v1 (
        tenant_scope TEXT NOT NULL,
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
        CONSTRAINT pg_llm_batch_outbox_payload_probe_v1
            CHECK (
                tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                AND evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                AND event_type ~ '^[a-z][a-z0-9._:-]{0,127}$'
                AND tenant_scope_sha256 ~ '^[0-9a-f]{64}$'
                AND subject_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND authority_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND origin_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND truth_status IN (
                    'authoritative',
                    'observed',
                    'inferred',
                    'proposed',
                    'superseded',
                    'rejected'
                )
                AND provenance_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND evidence_ref_sha256 ~ '^[0-9a-f]{64}$'
            ),
        CONSTRAINT pg_llm_batch_outbox_valid_time_probe_v1
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
            ),
        CONSTRAINT pg_llm_batch_outbox_system_time_probe_v1
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
            )
    ) ON COMMIT DROP;

    SELECT pg_catalog.pg_get_expr(conbin, conrelid, false)
    INTO STRICT canonical_payload_check_expression
    FROM pg_constraint
    WHERE conrelid = 'pg_temp.pg_llm_batch_outbox_constraint_probe_v1'::regclass
      AND conname = 'pg_llm_batch_outbox_payload_probe_v1';

    SELECT pg_catalog.pg_get_expr(conbin, conrelid, false)
    INTO STRICT canonical_valid_time_check_expression
    FROM pg_constraint
    WHERE conrelid = 'pg_temp.pg_llm_batch_outbox_constraint_probe_v1'::regclass
      AND conname = 'pg_llm_batch_outbox_valid_time_probe_v1';

    SELECT pg_catalog.pg_get_expr(conbin, conrelid, false)
    INTO STRICT canonical_system_time_check_expression
    FROM pg_constraint
    WHERE conrelid = 'pg_temp.pg_llm_batch_outbox_constraint_probe_v1'::regclass
      AND conname = 'pg_llm_batch_outbox_system_time_probe_v1';

    DROP TABLE pg_temp.pg_llm_batch_outbox_constraint_probe_v1;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_payload_canonical_v1'
          AND contype = 'c'
          AND convalidated
          AND NOT connoinherit
          AND pg_catalog.pg_get_expr(conbin, conrelid, false) =
              canonical_payload_check_expression
          AND pg_catalog.obj_description(oid, 'pg_constraint') =
              'pg-llm-batch:payload-check:v1:sha256=29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a'
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
              AND conname = 'ck_llm_context_lifecycle_outbox_payload_canonical_v1'
        ) THEN
            ALTER TABLE llm_context_lifecycle_outbox
                DROP CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1;
        END IF;

        ALTER TABLE llm_context_lifecycle_outbox
            ADD CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1
            CHECK (
                tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                AND evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                AND event_type ~ '^[a-z][a-z0-9._:-]{0,127}$'
                AND tenant_scope_sha256 ~ '^[0-9a-f]{64}$'
                AND subject_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND authority_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND origin_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND truth_status IN (
                    'authoritative',
                    'observed',
                    'inferred',
                    'proposed',
                    'superseded',
                    'rejected'
                )
                AND provenance_ref_sha256 ~ '^[0-9a-f]{64}$'
                AND evidence_ref_sha256 ~ '^[0-9a-f]{64}$'
            );
        COMMENT ON CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1
            ON llm_context_lifecycle_outbox
            IS 'pg-llm-batch:payload-check:v1:sha256=29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_payload_canonical_v1'
          AND contype = 'c'
          AND convalidated
          AND NOT connoinherit
          AND pg_catalog.pg_get_expr(conbin, conrelid, false) =
              canonical_payload_check_expression
          AND pg_catalog.obj_description(oid, 'pg_constraint') =
              'pg-llm-batch:payload-check:v1:sha256=29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a'
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox payload CHECK failed canonical verification';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_tenant_scope'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_tenant_scope;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_evidence_id'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_evidence_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_event_type'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_event_type;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_tenant_sha256'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_tenant_sha256;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_subject_sha256'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_subject_sha256;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_authority_sha256'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_authority_sha256;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_origin_sha256'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_origin_sha256;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_truth_status'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_truth_status;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_provenance_sha256'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_provenance_sha256;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_evidence_sha256'
    ) THEN
        ALTER TABLE llm_context_lifecycle_outbox
            DROP CONSTRAINT ck_llm_context_lifecycle_outbox_evidence_sha256;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1'
          AND contype = 'c'
          AND convalidated
          AND NOT connoinherit
          AND pg_catalog.pg_get_expr(conbin, conrelid, false) =
              canonical_valid_time_check_expression
          AND pg_catalog.obj_description(oid, 'pg_constraint') =
              'pg-llm-batch:timestamp-check:v1:sha256=32c3d6803b1c13e584230dcb0652bf8f932ee3ee256109dd25ed7d07e11d0261'
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
              AND conname = 'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1'
        ) THEN
            ALTER TABLE llm_context_lifecycle_outbox
                DROP CONSTRAINT ck_llm_context_lifecycle_outbox_valid_time_canonical_v1;
        END IF;

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
        COMMENT ON CONSTRAINT ck_llm_context_lifecycle_outbox_valid_time_canonical_v1
            ON llm_context_lifecycle_outbox
            IS 'pg-llm-batch:timestamp-check:v1:sha256=32c3d6803b1c13e584230dcb0652bf8f932ee3ee256109dd25ed7d07e11d0261';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1'
          AND contype = 'c'
          AND convalidated
          AND NOT connoinherit
          AND pg_catalog.pg_get_expr(conbin, conrelid, false) =
              canonical_valid_time_check_expression
          AND pg_catalog.obj_description(oid, 'pg_constraint') =
              'pg-llm-batch:timestamp-check:v1:sha256=32c3d6803b1c13e584230dcb0652bf8f932ee3ee256109dd25ed7d07e11d0261'
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox valid_time CHECK failed canonical verification';
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
          AND contype = 'c'
          AND convalidated
          AND NOT connoinherit
          AND pg_catalog.pg_get_expr(conbin, conrelid, false) =
              canonical_system_time_check_expression
          AND pg_catalog.obj_description(oid, 'pg_constraint') =
              'pg-llm-batch:timestamp-check:v1:sha256=490658f6948499784f4c86d642ff38a680821c50d31ad2627d6af10e02722ede'
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
              AND conname = 'ck_llm_context_lifecycle_outbox_system_time_canonical_v1'
        ) THEN
            ALTER TABLE llm_context_lifecycle_outbox
                DROP CONSTRAINT ck_llm_context_lifecycle_outbox_system_time_canonical_v1;
        END IF;

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
        COMMENT ON CONSTRAINT ck_llm_context_lifecycle_outbox_system_time_canonical_v1
            ON llm_context_lifecycle_outbox
            IS 'pg-llm-batch:timestamp-check:v1:sha256=490658f6948499784f4c86d642ff38a680821c50d31ad2627d6af10e02722ede';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass
          AND conname = 'ck_llm_context_lifecycle_outbox_system_time_canonical_v1'
          AND contype = 'c'
          AND convalidated
          AND NOT connoinherit
          AND pg_catalog.pg_get_expr(conbin, conrelid, false) =
              canonical_system_time_check_expression
          AND pg_catalog.obj_description(oid, 'pg_constraint') =
              'pg-llm-batch:timestamp-check:v1:sha256=490658f6948499784f4c86d642ff38a680821c50d31ad2627d6af10e02722ede'
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox system_time CHECK failed canonical verification';
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
        FROM pg_catalog.pg_policy AS policy_row
        WHERE policy_row.polrelid = 'llm_context_lifecycle_outbox'::regclass
          AND policy_row.polname = 'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2'
          AND policy_row.polcmd = '*'
          AND policy_row.polpermissive
          AND policy_row.polroles = ARRAY[0::oid]
          AND pg_catalog.pg_get_expr(policy_row.polqual, policy_row.polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND pg_catalog.pg_get_expr(policy_row.polwithcheck, policy_row.polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS unexpected_policy_dependency
              WHERE unexpected_policy_dependency.classid OPERATOR(pg_catalog.=)
                    'pg_catalog.pg_policy'::pg_catalog.regclass
                AND unexpected_policy_dependency.objid OPERATOR(pg_catalog.=)
                    policy_row.oid
                AND unexpected_policy_dependency.objsubid OPERATOR(pg_catalog.=) 0
                AND unexpected_policy_dependency.refobjsubid OPERATOR(pg_catalog.=) 0
                AND unexpected_policy_dependency.deptype::pg_catalog.text OPERATOR(pg_catalog.=) 'n'
                AND (
                    (
                        unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=)
                            'pg_catalog.pg_proc'::pg_catalog.regclass
                        AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>)
                            'pg_catalog.current_setting(pg_catalog.text,pg_catalog.bool)'::pg_catalog.regprocedure
                    )
                    OR (
                        unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=)
                            'pg_catalog.pg_operator'::pg_catalog.regclass
                        AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>)
                            'pg_catalog.=(pg_catalog.text,pg_catalog.text)'::pg_catalog.regoperator
                    )
                )
          )
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
        FROM pg_catalog.pg_policy AS policy_row
        WHERE policy_row.polrelid = 'llm_context_lifecycle_outbox'::regclass
          AND policy_row.polname = 'plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2'
          AND policy_row.polcmd = '*'
          AND policy_row.polpermissive
          AND policy_row.polroles = ARRAY[0::oid]
          AND pg_catalog.pg_get_expr(policy_row.polqual, policy_row.polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND pg_catalog.pg_get_expr(policy_row.polwithcheck, policy_row.polrelid, false) =
              '(tenant_scope = current_setting(''pg_llm_batch.tenant_scope''::text, true))'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS unexpected_policy_dependency
              WHERE unexpected_policy_dependency.classid OPERATOR(pg_catalog.=)
                    'pg_catalog.pg_policy'::pg_catalog.regclass
                AND unexpected_policy_dependency.objid OPERATOR(pg_catalog.=)
                    policy_row.oid
                AND unexpected_policy_dependency.objsubid OPERATOR(pg_catalog.=) 0
                AND unexpected_policy_dependency.refobjsubid OPERATOR(pg_catalog.=) 0
                AND unexpected_policy_dependency.deptype::pg_catalog.text OPERATOR(pg_catalog.=) 'n'
                AND (
                    (
                        unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=)
                            'pg_catalog.pg_proc'::pg_catalog.regclass
                        AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>)
                            'pg_catalog.current_setting(pg_catalog.text,pg_catalog.bool)'::pg_catalog.regprocedure
                    )
                    OR (
                        unexpected_policy_dependency.refclassid OPERATOR(pg_catalog.=)
                            'pg_catalog.pg_operator'::pg_catalog.regclass
                        AND unexpected_policy_dependency.refobjid OPERATOR(pg_catalog.<>)
                            'pg_catalog.=(pg_catalog.text,pg_catalog.text)'::pg_catalog.regoperator
                    )
                )
          )
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

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS operational_index
        JOIN pg_class AS index_relation
          ON index_relation.oid = operational_index.indexrelid
        JOIN pg_am AS index_method
          ON index_method.oid = index_relation.relam
        WHERE operational_index.indrelid =
              'llm_context_lifecycle_outbox'::regclass
          AND index_relation.relname = 'idx_llm_context_lifecycle_outbox_tenant_created'
          AND index_relation.relnamespace = 'public'::regnamespace
          AND index_method.amname = 'btree'
          AND operational_index.indisvalid
          AND operational_index.indisready
          AND operational_index.indislive
          AND NOT operational_index.indisunique
          AND operational_index.indnkeyatts = 2
          AND operational_index.indnatts = 2
          AND operational_index.indexprs IS NULL
          AND operational_index.indpred IS NULL
          AND operational_index.indkey[0] = (
              SELECT attnum
              FROM pg_attribute
              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                AND attname = 'tenant_scope'
                AND NOT attisdropped
          )
          AND operational_index.indkey[1] = (
              SELECT attnum
              FROM pg_attribute
              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                AND attname = 'created_at'
                AND NOT attisdropped
          )
          AND operational_index.indcollation[0] = (
              SELECT attcollation
              FROM pg_attribute
              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                AND attname = 'tenant_scope'
                AND NOT attisdropped
          )
          AND operational_index.indcollation[1] = 0
          AND operational_index.indclass[0] = (
              SELECT opclass.oid
              FROM pg_opclass AS opclass
              JOIN pg_am AS opclass_method
                ON opclass_method.oid = opclass.opcmethod
              WHERE opclass_method.amname = 'btree'
                AND opclass.opcdefault
                AND opclass.opcintype = 'text'::regtype
          )
          AND operational_index.indclass[1] = (
              SELECT opclass.oid
              FROM pg_opclass AS opclass
              JOIN pg_am AS opclass_method
                ON opclass_method.oid = opclass.opcmethod
              WHERE opclass_method.amname = 'btree'
                AND opclass.opcdefault
                AND opclass.opcintype = 'timestamptz'::regtype
          )
          AND operational_index.indoption[0] = 0
          AND operational_index.indoption[1] = 0
    ) THEN
        IF pg_catalog.to_regclass(
            'public.idx_llm_context_lifecycle_outbox_tenant_created'
        ) IS NOT NULL THEN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_index
                WHERE indexrelid = pg_catalog.to_regclass(
                    'public.idx_llm_context_lifecycle_outbox_tenant_created'
                )
                  AND indrelid = 'llm_context_lifecycle_outbox'::regclass
            ) THEN
                RAISE EXCEPTION 'lifecycle outbox operational index name collision';
            END IF;
            DROP INDEX public.idx_llm_context_lifecycle_outbox_tenant_created;
        END IF;

        CREATE INDEX idx_llm_context_lifecycle_outbox_tenant_created
            ON public.llm_context_lifecycle_outbox(tenant_scope, created_at);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS operational_index
        JOIN pg_class AS index_relation
          ON index_relation.oid = operational_index.indexrelid
        JOIN pg_am AS index_method
          ON index_method.oid = index_relation.relam
        WHERE operational_index.indrelid =
              'llm_context_lifecycle_outbox'::regclass
          AND index_relation.relname = 'idx_llm_context_lifecycle_outbox_tenant_created'
          AND index_relation.relnamespace = 'public'::regnamespace
          AND index_method.amname = 'btree'
          AND operational_index.indisvalid
          AND operational_index.indisready
          AND operational_index.indislive
          AND NOT operational_index.indisunique
          AND operational_index.indnkeyatts = 2
          AND operational_index.indnatts = 2
          AND operational_index.indexprs IS NULL
          AND operational_index.indpred IS NULL
          AND operational_index.indkey[0] = (
              SELECT attnum
              FROM pg_attribute
              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                AND attname = 'tenant_scope'
                AND NOT attisdropped
          )
          AND operational_index.indkey[1] = (
              SELECT attnum
              FROM pg_attribute
              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                AND attname = 'created_at'
                AND NOT attisdropped
          )
          AND operational_index.indcollation[0] = (
              SELECT attcollation
              FROM pg_attribute
              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass
                AND attname = 'tenant_scope'
                AND NOT attisdropped
          )
          AND operational_index.indcollation[1] = 0
          AND operational_index.indclass[0] = (
              SELECT opclass.oid
              FROM pg_opclass AS opclass
              JOIN pg_am AS opclass_method
                ON opclass_method.oid = opclass.opcmethod
              WHERE opclass_method.amname = 'btree'
                AND opclass.opcdefault
                AND opclass.opcintype = 'text'::regtype
          )
          AND operational_index.indclass[1] = (
              SELECT opclass.oid
              FROM pg_opclass AS opclass
              JOIN pg_am AS opclass_method
                ON opclass_method.oid = opclass.opcmethod
              WHERE opclass_method.amname = 'btree'
                AND opclass.opcdefault
                AND opclass.opcintype = 'timestamptz'::regtype
          )
          AND operational_index.indoption[0] = 0
          AND operational_index.indoption[1] = 0
    ) THEN
        RAISE EXCEPTION 'lifecycle outbox operational index failed canonical verification';
    END IF;
END $$;
