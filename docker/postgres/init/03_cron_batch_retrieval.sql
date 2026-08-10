-- SPDX-License-Identifier: Apache-2.0
-- Decommission the legacy pg_cron + pgsql-http provider retrieval path.
--
-- Provider HTTP authority belongs to the Python BatchAPIClient / DurableBatchAPIClient
-- boundary, which validates endpoint authority, remote resource identifiers,
-- credential handling, response bounds, retry semantics, and durable lifecycle state.
-- The former SQL retriever could not preserve those contracts and also treated a
-- local llm_batches.batch_uuid as though it were a provider remote batch ID.
--
-- Fresh standalone databases execute this file after pg_cron is installed and
-- therefore never create the legacy job/functions. Existing deployments may replay
-- this file with the same job owner (or a superuser) to remove future executions.
-- Existing gateway_retrieval_logs data is intentionally retained for audit/history.

DO $$
DECLARE
    legacy_job RECORD;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_extension
        WHERE extname = 'pg_cron'
    ) THEN
        FOR legacy_job IN
            SELECT jobid
            FROM cron.job
            WHERE jobname = 'batch-result-retrieval'
              AND command = 'SELECT cron_fetch_batch_results();'
        LOOP
            PERFORM cron.unschedule(legacy_job.jobid);
        END LOOP;
    END IF;
END
$$;

DROP FUNCTION IF EXISTS public.cron_fetch_batch_results();
DROP FUNCTION IF EXISTS public.import_batch_results_jsonl(UUID, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.get_secret_value(TEXT);
DROP FUNCTION IF EXISTS public.get_config_value(TEXT);
