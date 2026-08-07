-- SPDX-License-Identifier: Apache-2.0
-- Refuse destructive rollback while accepted checkpoint audit evidence exists.

DO $$
BEGIN
    IF to_regclass('llm_result_checkpoint_audit_events') IS NOT NULL THEN
        -- FORCE RLS would hide rows when no tenant scope is bound. A role that
        -- can drop this table must temporarily become subject to the ordinary
        -- owner-bypass rule so the emptiness check sees every tenant. A raised
        -- exception rolls this relaxation back with the surrounding transaction.
        ALTER TABLE llm_result_checkpoint_audit_events NO FORCE ROW LEVEL SECURITY;

        IF EXISTS (
            SELECT 1 FROM llm_result_checkpoint_audit_events LIMIT 1
        ) THEN
            RAISE EXCEPTION
                'Refusing to drop non-empty llm_result_checkpoint_audit_events; export retained audit evidence first'
                USING ERRCODE = '55000';
        END IF;
    END IF;

    DROP TABLE IF EXISTS llm_result_checkpoint_audit_events;
    DROP FUNCTION IF EXISTS reject_checkpoint_audit_mutation();
END $$;
