-- SPDX-License-Identifier: Apache-2.0
-- Refuse destructive rollback while durable acknowledgement evidence exists.

DO $$
BEGIN
    IF to_regclass('llm_result_stream_checkpoints') IS NOT NULL AND EXISTS (
        SELECT 1 FROM llm_result_stream_checkpoints LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'Refusing to drop non-empty llm_result_stream_checkpoints; export or reconcile checkpoints first'
            USING ERRCODE = '55000';
    END IF;

    DROP TABLE IF EXISTS llm_result_stream_checkpoints;
END $$;
