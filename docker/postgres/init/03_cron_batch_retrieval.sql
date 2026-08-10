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
-- mode; this block removes a helper only when pg_proc retains the exact retired
-- PL/pgSQL source body plus the reviewed language/volatility/invoker-security shape.
-- Characteristic substring markers are deliberately insufficient because modified
-- operator code can preserve those markers while changing behavior.
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
           OR helper_source IS DISTINCT FROM $legacy$
DECLARE
    base_url TEXT;
    api_key TEXT;
    rec RECORD;
    start_ts TIMESTAMPTZ;
    res http_response;
    status TEXT;
    output_id TEXT;
BEGIN
    base_url := get_config_value('gateway.base_url');
    api_key := get_secret_value('gateway_api_key.default');
    IF base_url IS NULL OR api_key IS NULL THEN
        INSERT INTO gateway_retrieval_logs(status, error)
        VALUES ('error', 'Missing gateway.base_url or gateway_api_key.default');
        RETURN;
    END IF;

    FOR rec IN
        SELECT b.batch_uuid, b.batch_uuid::text AS gateway_batch_id,
               b.input_file_path AS input_file_id
        FROM llm_batches b
        WHERE b.batch_status IN ('validating', 'in_progress', 'finalizing', 'processing')
    LOOP
        start_ts := clock_timestamp();
        res := http_get(rtrim(base_url, '/') || '/v1/batches/' || rec.gateway_batch_id,
                        ARRAY[http_header('Authorization', 'Bearer ' || api_key)]);
        status := NULL;
        output_id := NULL;
        BEGIN
            status := (res.content::json)->>'status';
            output_id := (res.content::json)->>'output_file_id';
        EXCEPTION WHEN others THEN
            status := NULL;
        END;
        INSERT INTO gateway_retrieval_logs(batch_uuid, input_file_id, status, http_code, latency_ms)
        VALUES (rec.batch_uuid, rec.input_file_id, COALESCE(status, 'unknown'),
                res.status, EXTRACT(MILLISECOND FROM clock_timestamp() - start_ts)::int);

        IF status IN ('completed', 'succeeded', 'done') AND output_id IS NOT NULL THEN
            res := http_get(rtrim(base_url, '/') || '/v1/files/' || output_id || '/content',
                            ARRAY[http_header('Authorization', 'Bearer ' || api_key)]);
            PERFORM import_batch_results_jsonl(rec.batch_uuid, output_id, res.content);
            UPDATE llm_batches SET batch_status = 'completed', updated_at = NOW()
             WHERE batch_uuid = rec.batch_uuid;
            INSERT INTO gateway_retrieval_logs(batch_uuid, output_file_id, status, http_code)
            VALUES (rec.batch_uuid, output_id, 'imported', res.status);
        END IF;
    END LOOP;
END;
$legacy$ THEN
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
           OR helper_source IS DISTINCT FROM $legacy$
DECLARE
    updated_count INTEGER := 0;
    line TEXT;
    obj JSONB;
    custom_id TEXT;
    response JSONB;
    usage JSONB;
BEGIN
    FOR line IN SELECT * FROM regexp_split_to_table(COALESCE(p_content, ''), E'\n') LOOP
        line := btrim(line);
        CONTINUE WHEN line = '';
        BEGIN
            obj := line::jsonb;
        EXCEPTION WHEN others THEN
            CONTINUE;
        END;
        custom_id := obj->>'custom_id';
        CONTINUE WHEN custom_id IS NULL OR custom_id = '';
        response := obj->'response'->'body';
        usage := response->'usage';
        UPDATE llm_requests
           SET request_status = 'completed',
               response_content = response->'choices'->0->'message'->>'content',
               response_metadata = obj,
               prompt_tokens = COALESCE((usage->>'prompt_tokens')::INT, prompt_tokens),
               completion_tokens = COALESCE((usage->>'completion_tokens')::INT, completion_tokens),
               total_tokens = COALESCE((usage->>'total_tokens')::INT, total_tokens),
               completed_at = NOW()
         WHERE request_uuid = custom_id::uuid;
        IF FOUND THEN
            updated_count := updated_count + 1;
        END IF;
    END LOOP;
    RETURN updated_count;
END;
$legacy$ THEN
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
           OR helper_source IS DISTINCT FROM $legacy$
DECLARE
    rec RECORD;
BEGIN
    SELECT secret_value, is_encrypted INTO rec
    FROM com_secrets WHERE secret_key = p_key LIMIT 1;
    IF rec IS NULL THEN
        RETURN NULL;
    END IF;
    IF rec.is_encrypted THEN
        -- Encrypted at rest; cannot decrypt inside SQL without the app key.
        RETURN NULL;
    END IF;
    RETURN convert_from(decode(rec.secret_value, 'base64'), 'UTF8');
END;
$legacy$ THEN
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
           OR helper_source IS DISTINCT FROM $legacy$
DECLARE
    v TEXT;
BEGIN
    SELECT config_value INTO v FROM com_config WHERE config_key = p_key LIMIT 1;
    RETURN v;
END;
$legacy$ THEN
            RAISE EXCEPTION 'Refusing to drop public.get_config_value(text): definition does not match the retired legacy helper'
                USING ERRCODE = '55000',
                      HINT = 'Review the same-signature function manually; unrelated operator code is never deleted by signature alone.';
        END IF;
        EXECUTE 'DROP FUNCTION public.get_config_value(text)';
    END IF;
END
$$;