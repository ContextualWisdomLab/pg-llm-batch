-- SPDX-License-Identifier: Apache-2.0
-- Refuse destructive rollback while durable acknowledgement evidence exists.

DO $$
BEGIN
    IF to_regclass('llm_result_stream_checkpoints') IS NOT NULL THEN
        -- FORCE RLS would hide every row when no tenant setting is bound. A role
        -- capable of dropping this table must first become subject to the normal
        -- owner-bypass rule so the emptiness check observes every tenant. The DO
        -- block is one transaction: a raised exception rolls this relaxation back.
        ALTER TABLE llm_result_stream_checkpoints NO FORCE ROW LEVEL SECURITY;

        IF EXISTS (
            SELECT 1 FROM llm_result_stream_checkpoints LIMIT 1
        ) THEN
            RAISE EXCEPTION
                'Refusing to drop non-empty llm_result_stream_checkpoints; export or reconcile checkpoints first'
                USING ERRCODE = '55000';
        END IF;
    END IF;

    DROP TABLE IF EXISTS llm_result_stream_checkpoints;
END $$;
