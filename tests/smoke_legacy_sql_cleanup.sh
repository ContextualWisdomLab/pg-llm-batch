#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-sql-cleanup-${GITHUB_RUN_ID:-local}-$$"
cleanup_sql="/docker-entrypoint-initdb.d/03_cron_batch_retrieval.sql"

cleanup() {
  docker rm --force "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach \
  --name "${container}" \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  "${image}" >/dev/null

# The official PostgreSQL image runs a temporary Unix-socket-only server while
# executing init scripts, then shuts it down before starting the final server.
# Waiting only for a table over the Unix socket can therefore race that planned
# shutdown. Require TCP readiness first; the temporary init server explicitly
# has listen_addresses='' and cannot satisfy this boundary.
ready=0
for _ in $(seq 1 60); do
  if docker exec "${container}" pg_isready -h 127.0.0.1 -U postgres -d postgres \
      >/dev/null 2>&1 && \
     docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres -Atqc \
      "SELECT (to_regclass('public.llm_batches') IS NOT NULL)::int" 2>/dev/null \
      | grep -qx '1'; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  docker logs "${container}" >&2 || true
  echo "fresh PostgreSQL image did not finish final-server initialization" >&2
  exit 1
fi

# Fresh installations must keep only the required crypto boundary and must not
# create database-side provider scheduling/network authority.
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_extension WHERE extname = 'pgcrypto'")" = "1"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_extension WHERE extname IN ('pg_cron', 'http')")" = "0"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_proc WHERE oid IN (\
     to_regprocedure('public.cron_fetch_batch_results()'),\
     to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)'),\
     to_regprocedure('public.get_secret_value(text)'),\
     to_regprocedure('public.get_config_value(text)')\
   )")" = "0"

# Model an existing installation using the actual retired function definitions.
# The far-future schedule makes the fixture inert while preserving the exact job
# name+command identity that cleanup is authorized to unschedule.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
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

CREATE OR REPLACE FUNCTION get_config_value(p_key TEXT)
RETURNS TEXT AS $$
DECLARE
    v TEXT;
BEGIN
    SELECT config_value INTO v FROM com_config WHERE config_key = p_key LIMIT 1;
    RETURN v;
END;
$$ LANGUAGE plpgsql STABLE;

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
    '0 0 1 1 *',
    $$SELECT cron_fetch_batch_results();$$
);
SQL

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${cleanup_sql}"

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM cron.job WHERE jobname = 'batch-result-retrieval' AND command = 'SELECT cron_fetch_batch_results();'")" = "0"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_proc WHERE oid IN (\
     to_regprocedure('public.cron_fetch_batch_results()'),\
     to_regprocedure('public.import_batch_results_jsonl(uuid,text,text)'),\
     to_regprocedure('public.get_secret_value(text)'),\
     to_regprocedure('public.get_config_value(text)')\
   )")" = "0"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT (to_regclass('public.gateway_retrieval_logs') IS NOT NULL)::int")" = "1"

# A substituted same-signature operator function is not deletion authority. The
# exact job must still be unscheduled first, then cleanup must fail closed and
# preserve the operator function for manual review.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE FUNCTION public.get_config_value(text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$SELECT $1$$;

SELECT cron.schedule(
    'batch-result-retrieval',
    '0 0 1 1 *',
    $$SELECT cron_fetch_batch_results();$$
);
SQL

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${cleanup_sql}"; then
  echo "cleanup unexpectedly deleted or accepted a substituted helper" >&2
  exit 1
fi

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM cron.job WHERE jobname = 'batch-result-retrieval' AND command = 'SELECT cron_fetch_batch_results();'")" = "0"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT to_regprocedure('public.get_config_value(text)') IS NOT NULL")" = "t"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT public.get_config_value('operator-value')")" = "operator-value"

# Matching only characteristic body markers is still unsafe: an operator can
# intentionally extend the old PL/pgSQL helper while preserving every marker
# used by a substring classifier. Any definition change must remain operator
# owned and fail closed instead of being deleted as though it were the exact
# retired helper.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP FUNCTION public.get_config_value(text);
CREATE FUNCTION public.get_config_value(p_key text)
RETURNS text AS $$
DECLARE
    v text;
BEGIN
    IF p_key = 'operator-marker' THEN
        RETURN 'operator-preserved';
    END IF;
    SELECT config_value INTO v FROM com_config WHERE config_key = p_key LIMIT 1;
    RETURN v;
END;
$$ LANGUAGE plpgsql STABLE;

SELECT cron.schedule(
    'batch-result-retrieval',
    '0 0 1 1 *',
    $$SELECT cron_fetch_batch_results();$$
);
SQL

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${cleanup_sql}"; then
  echo "cleanup unexpectedly accepted a marker-preserving modified helper" >&2
  exit 1
fi

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM cron.job WHERE jobname = 'batch-result-retrieval' AND command = 'SELECT cron_fetch_batch_results();'")" = "0"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT to_regprocedure('public.get_config_value(text)') IS NOT NULL")" = "t"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT public.get_config_value('operator-marker')")" = "operator-preserved"

# The preceding cases prove that cleanup preserves operator-modified helpers.
# Remove only the fixture-owned substitute before exercising extension retirement.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "DROP FUNCTION public.get_config_value(text);"

# A live operator cron schedule is independent authority. Retirement must refuse
# it, preserve both extensions, and leave application evidence untouched.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT cron.schedule(
    'operator-maintenance',
    '0 0 1 1 *',
    $$SELECT 1;$$
);
SQL

if docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    < docker/postgres/migrations/retire_legacy_provider_extensions.sql; then
  echo "retirement unexpectedly accepted an unrelated cron job" >&2
  exit 1
fi

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM cron.job WHERE jobname = 'operator-maintenance'")" = "1"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_extension WHERE extname IN ('pg_cron', 'http')")" = "2"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT (to_regclass('public.gateway_retrieval_logs') IS NOT NULL)::int")" = "1"

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT cron.unschedule(jobid) FROM cron.job WHERE jobname = 'operator-maintenance';"

# RESTRICT still drops objects explicitly enrolled as extension members. Model
# an accidental application-table enrollment and prove the migration rejects it
# before the table or either extension can be removed.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER EXTENSION http ADD TABLE gateway_retrieval_logs;"

if docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    < docker/postgres/migrations/retire_legacy_provider_extensions.sql; then
  echo "retirement unexpectedly accepted an application extension member" >&2
  exit 1
fi

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT (to_regclass('public.gateway_retrieval_logs') IS NOT NULL)::int")" = "1"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_extension WHERE extname IN ('pg_cron', 'http')")" = "2"

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER EXTENSION http DROP TABLE gateway_retrieval_logs;"

# DEPENDS ON EXTENSION creates an auto-extension dependency that is also dropped
# under RESTRICT. Preserve such operator-owned routines for explicit disposition.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE FUNCTION public.operator_retirement_dependency()
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$SELECT 1$$;
ALTER FUNCTION public.operator_retirement_dependency() DEPENDS ON EXTENSION http;
SQL

if docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    < docker/postgres/migrations/retire_legacy_provider_extensions.sql; then
  echo "retirement unexpectedly accepted an explicit extension dependency" >&2
  exit 1
fi

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT to_regprocedure('public.operator_retirement_dependency()') IS NOT NULL")" = "t"
test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_extension WHERE extname IN ('pg_cron', 'http')")" = "2"

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER FUNCTION public.operator_retirement_dependency() NO DEPENDS ON EXTENSION http;
DROP FUNCTION public.operator_retirement_dependency();
SQL

# Once every legacy helper, cron schedule, unexpected member, and explicit
# extension dependency is absent, retirement may remove only the two intended
# extension-owned surfaces. Repeating the migration is idempotent.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < docker/postgres/migrations/retire_legacy_provider_extensions.sql

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_extension WHERE extname IN ('pg_cron', 'http')")" = "0"
if [[ "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT (to_regclass('public.gateway_retrieval_logs') IS NOT NULL)::int")" != "1" ]]; then
  echo "retirement unexpectedly removed gateway_retrieval_logs" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < docker/postgres/migrations/retire_legacy_provider_extensions.sql
