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

-- Function names/signatures are not sufficient deletion authority. An operator may
-- have replaced one of these generic public helpers after the legacy installer ran.
-- Unscheduling above is committed independently by psql in its normal autocommit
-- mode; this block then removes only definitions that still retain the retired
-- helper's characteristic body, language, volatility, and invoker-security shape.
DO $$
DECLARE
    helper_oid OID;
    helper_source TEXT;
    helper_language NAME;
    helper_volatility "char";
    helper_security_definer BOOLEAN;
BEGIN
    helper_oid := to_regprocedure('public.cron_fetch_batch_results()');
    IF helper_oid IS NOT NULL THEN
        SELECT p.prosrc, l.lanname, p.provolatile, p.prosecdef
          INTO helper_source, helper_language, helper_volatility, helper_security_definer
          FROM pg_catalog.pg_proc AS p
          JOIN pg_catalog.pg_language AS l ON l.oid = p.prolang
         WHERE p.oid = helper_oid;
        IF helper_language <> 'plpgsql'
           OR helper_volatility <> 'v'
           OR helper_security_definer
           OR position('gateway_api_key.default' IN helper_source) = 0
           OR position('llm_batches' IN helper_source) = 0
           OR position('import_batch_results_jsonl' IN helper_source) = 0 THEN
            RAISE EXCEPTION 'Refusing to drop public.cron_fetch_batch_results(): definition does not match the retired legacy helper'
                USING ERRCODE = '55000',
                      HINT = 'Review the same-signature function manually; the legacy cron job has already been unscheduled when this file is run with psql autocommit.';
        END IF;
        EXECUTE 'DROP FUNCTION public.cron_fetch_batch_results()';
    END IF;

    helper_oid := to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)');
    IF helper_oid IS NOT NULL THEN
        SELECT p.prosrc, l.lanname, p.provolatile, p.prosecdef
          INTO helper_source, helper_language, helper_volatility, helper_security_definer
          FROM pg_catalog.pg_proc AS p
          JOIN pg_catalog.pg_language AS l ON l.oid = p.prolang
         WHERE p.oid = helper_oid;
        IF helper_language <> 'plpgsql'
           OR helper_volatility <> 'v'
           OR helper_security_definer
           OR position('llm_requests' IN helper_source) = 0
           OR position('request_status = ''completed''' IN helper_source) = 0
           OR position('response_metadata = obj' IN helper_source) = 0 THEN
            RAISE EXCEPTION 'Refusing to drop public.import_batch_results_jsonl(uuid,text,text): definition does not match the retired legacy helper'
                USING ERRCODE = '55000',
                      HINT = 'Review the same-signature function manually; unrelated operator code is never deleted by signature alone.';
        END IF;
        EXECUTE 'DROP FUNCTION public.import_batch_results_jsonl(uuid,text,text)';
    END IF;

    helper_oid := to_regprocedure('public.get_secret_value(text)');
    IF helper_oid IS NOT NULL THEN
        SELECT p.prosrc, l.lanname, p.provolatile, p.prosecdef
          INTO helper_source, helper_language, helper_volatility, helper_security_definer
          FROM pg_catalog.pg_proc AS p
          JOIN pg_catalog.pg_language AS l ON l.oid = p.prolang
         WHERE p.oid = helper_oid;
        IF helper_language <> 'plpgsql'
           OR helper_volatility <> 's'
           OR helper_security_definer
           OR position('com_secrets' IN helper_source) = 0
           OR position('rec.is_encrypted' IN helper_source) = 0
           OR position('decode(rec.secret_value, ''base64'')' IN helper_source) = 0 THEN
            RAISE EXCEPTION 'Refusing to drop public.get_secret_value(text): definition does not match the retired legacy helper'
                USING ERRCODE = '55000',
                      HINT = 'Review the same-signature function manually; unrelated operator code is never deleted by signature alone.';
        END IF;
        EXECUTE 'DROP FUNCTION public.get_secret_value(text)';
    END IF;

    helper_oid := to_regprocedure('public.get_config_value(text)');
    IF helper_oid IS NOT NULL THEN
        SELECT p.prosrc, l.lanname, p.provolatile, p.prosecdef
          INTO helper_source, helper_language, helper_volatility, helper_security_definer
          FROM pg_catalog.pg_proc AS p
          JOIN pg_catalog.pg_language AS l ON l.oid = p.prolang
         WHERE p.oid = helper_oid;
        IF helper_language <> 'plpgsql'
           OR helper_volatility <> 's'
           OR helper_security_definer
           OR position('com_config' IN helper_source) = 0
           OR position('config_key = p_key' IN helper_source) = 0 THEN
            RAISE EXCEPTION 'Refusing to drop public.get_config_value(text): definition does not match the retired legacy helper'
                USING ERRCODE = '55000',
                      HINT = 'Review the same-signature function manually; unrelated operator code is never deleted by signature alone.';
        END IF;
        EXECUTE 'DROP FUNCTION public.get_config_value(text)';
    END IF;
END
$$;
