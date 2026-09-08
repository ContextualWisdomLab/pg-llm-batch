-- SPDX-License-Identifier: Apache-2.0
-- Refuse destructive rollback while lifecycle publication intent remains durable.

DO $$
BEGIN
    -- The rollback is destructive, so resolve only reviewed PostgreSQL/application
    -- schemas before inspecting or dropping the canonical outbox relation.
    PERFORM pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true);

    IF pg_catalog.to_regclass('llm_context_lifecycle_outbox') IS NOT NULL THEN
        -- FORCE RLS would hide rows when no tenant setting is bound. A role able to
        -- drop the table must first expose every tenant so the emptiness check is
        -- meaningful. The DO block is transactional, so a refusal restores FORCE RLS.
        ALTER TABLE llm_context_lifecycle_outbox NO FORCE ROW LEVEL SECURITY;

        IF EXISTS (
            SELECT 1 FROM llm_context_lifecycle_outbox LIMIT 1
        ) THEN
            RAISE EXCEPTION
                'Refusing to drop non-empty llm_context_lifecycle_outbox; publish, export, or reconcile lifecycle evidence first'
                USING ERRCODE = '55000';
        END IF;
    END IF;

    DROP TABLE IF EXISTS llm_context_lifecycle_outbox;
END $$;
