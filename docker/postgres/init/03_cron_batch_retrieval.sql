-- SPDX-License-Identifier: Apache-2.0
-- pg_cron + http based batch result retrieval and import.
-- Requires com_config entries: gateway.base_url, and secret gateway_api_key.<alias>.
-- The gateway credentials are read from the KV stores (never os.getenv).

CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS http;

CREATE TABLE IF NOT EXISTS gateway_retrieval_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_uuid UUID,
    input_file_id TEXT,
    output_file_id TEXT,
    status TEXT,
    http_code INT,
    latency_ms INT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Read a plain config value out of the com_config KV table.
CREATE OR REPLACE FUNCTION get_config_value(p_key TEXT)
RETURNS TEXT AS $$
DECLARE
    v TEXT;
BEGIN
    SELECT config_value INTO v FROM com_config WHERE config_key = p_key LIMIT 1;
    RETURN v;
END;
$$ LANGUAGE plpgsql STABLE;

-- Read a secret. Only usable for base64-obfuscated (unencrypted) secrets from
-- inside SQL; Fernet-encrypted secrets are decrypted app-side. Local/dev
-- containers store the gateway key base64-only so the cron job can use it.
CREATE OR REPLACE FUNCTION get_secret_value(p_key TEXT)
RETURNS TEXT AS $$
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
$$ LANGUAGE plpgsql STABLE;

-- Import results JSONL: match custom_id -> request_uuid and record usage.
CREATE OR REPLACE FUNCTION import_batch_results_jsonl(
    p_batch_uuid UUID,
    p_output_file_id TEXT,
    p_content TEXT
) RETURNS INTEGER AS $$
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
$$ LANGUAGE plpgsql;

-- Poll submitted/in-progress batches, fetch output, import JSONL.
CREATE OR REPLACE FUNCTION cron_fetch_batch_results() RETURNS VOID AS $$
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
$$ LANGUAGE plpgsql;

SELECT cron.schedule(
    'batch-result-retrieval',
    '* * * * *',
    $$SELECT cron_fetch_batch_results();$$
)
WHERE NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'batch-result-retrieval');
