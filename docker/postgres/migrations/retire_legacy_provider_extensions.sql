-- SPDX-License-Identifier: Apache-2.0
-- Existing-volume preflight for retiring the legacy provider-network extensions.
-- Run 03_cron_batch_retrieval.sql first. This migration refuses extension
-- removal while the retired job, any independent cron job, or any retired helper
-- still exists. Extension dependency checks remain PostgreSQL-owned through
-- DROP EXTENSION ... RESTRICT.

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    legacy_job_count BIGINT := 0;
    remaining_job_count BIGINT := 0;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension
        WHERE extname = 'pg_cron'
    ) THEN
        EXECUTE $query$
            SELECT count(*)
            FROM cron.job
            WHERE jobname = 'batch-result-retrieval'
              AND command = 'SELECT cron_fetch_batch_results();'
        $query$
        INTO legacy_job_count;

        IF legacy_job_count <> 0 THEN
            RAISE EXCEPTION 'Refusing to retire pg_cron while the retired provider job remains scheduled'
                USING ERRCODE = '55000',
                      HINT = 'Run 03_cron_batch_retrieval.sql successfully before this migration.';
        END IF;

        EXECUTE 'SELECT count(*) FROM cron.job'
        INTO remaining_job_count;
        IF remaining_job_count <> 0 THEN
            RAISE EXCEPTION 'Refusing to retire pg_cron while cron jobs remain'
                USING ERRCODE = '55000',
                      HINT = 'Migrate or remove operator-owned cron jobs before retiring the extension.';
        END IF;
    END IF;

    IF to_regprocedure('public.cron_fetch_batch_results()') IS NOT NULL
       OR to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)') IS NOT NULL
       OR to_regprocedure('public.get_secret_value(text)') IS NOT NULL
       OR to_regprocedure('public.get_config_value(text)') IS NOT NULL THEN
        RAISE EXCEPTION 'Refusing to retire provider extensions while retired helper functions remain'
            USING ERRCODE = '55000',
                  HINT = 'Run 03_cron_batch_retrieval.sql successfully and review any substituted helper before retrying.';
    END IF;
END
$$;

DROP EXTENSION IF EXISTS http RESTRICT;
DROP EXTENSION IF EXISTS pg_cron RESTRICT;

COMMIT;
