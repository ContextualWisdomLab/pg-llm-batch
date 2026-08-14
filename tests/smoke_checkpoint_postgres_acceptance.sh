#!/usr/bin/env bash
set -euo pipefail

container="${1:?PostgreSQL container name is required}"
forward_sql="/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql"
rollback_sql="pg_llm_batch/migrations/rollback/0007_result_stream_checkpoints.sql"
empty_db="checkpoint_empty_rollback"
nonempty_db="checkpoint_nonempty_rollback"

psql_exec() {
  docker exec "${container}" psql -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1 "$@"
}

# A fresh deployable image must have executed the checkpoint migration rather
# than merely carrying a byte-identical SQL mirror in the build context.
test "$(psql_exec -d postgres -Atqc \
  "SELECT to_regclass('public.llm_result_stream_checkpoints')::text")" = \
  "llm_result_stream_checkpoints"
test "$(psql_exec -d postgres -Atqc \
  "SELECT relrowsecurity::text || ':' || relforcerowsecurity::text FROM pg_class WHERE oid = 'public.llm_result_stream_checkpoints'::regclass")" = \
  "true:true"

# Exercise FORCE RLS with a non-superuser role. Missing tenant authority and a
# different tenant must observe no rows, while a cross-tenant write fails closed.
psql_exec -d postgres -qc "CREATE ROLE checkpoint_runtime NOLOGIN"
psql_exec -d postgres -qc \
  "GRANT SELECT, INSERT, UPDATE ON llm_result_stream_checkpoints TO checkpoint_runtime"
psql_exec -d postgres -qc \
  "SET ROLE checkpoint_runtime; SET pg_llm_batch.tenant_scope = 'tenant-a'; INSERT INTO llm_result_stream_checkpoints (tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id, schema_version, file_kind, file_id, file_line_number, batch_line_count, record_count, prefix_sha256) VALUES ('tenant-a', 'consumer-a', 'default', 'batch-a', 1, 'result', 'file-a', 1, 1, 1, repeat('a', 64))"
test "$(psql_exec -d postgres -Atqc \
  "SET ROLE checkpoint_runtime; SELECT count(*) FROM llm_result_stream_checkpoints")" = "0"
test "$(psql_exec -d postgres -Atqc \
  "SET ROLE checkpoint_runtime; SET pg_llm_batch.tenant_scope = 'tenant-b'; SELECT count(*) FROM llm_result_stream_checkpoints")" = "0"
test "$(psql_exec -d postgres -Atqc \
  "SET ROLE checkpoint_runtime; SET pg_llm_batch.tenant_scope = 'tenant-a'; SELECT count(*) FROM llm_result_stream_checkpoints")" = "1"
if psql_exec -d postgres -qc \
  "SET ROLE checkpoint_runtime; SET pg_llm_batch.tenant_scope = 'tenant-b'; INSERT INTO llm_result_stream_checkpoints (tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id, schema_version, file_kind, file_id, file_line_number, batch_line_count, record_count, prefix_sha256) VALUES ('tenant-a', 'consumer-cross', 'default', 'batch-cross', 1, 'result', 'file-cross', 1, 1, 1, repeat('b', 64))" \
  >/dev/null 2>&1; then
  echo "Cross-tenant checkpoint write unexpectedly succeeded" >&2
  exit 1
fi

# Run the package store itself against the same live database. Sharing the
# PostgreSQL container network namespace keeps the database unexposed on the
# runner while the separately built component image supplies the installed
# package and locked Psycopg runtime used in production.
docker run --rm \
  --network "container:${container}" \
  --volume "${PWD}/tests:/tests:ro" \
  pg-llm-batch:ci \
  python /tests/smoke_checkpoint_store_concurrency.py

# Validate rollback behavior against real PostgreSQL in isolated databases. An
# empty store is removable; durable acknowledgement evidence makes rollback fail
# atomically and must leave FORCE RLS enabled after the failed transaction.
psql_exec -d postgres -qc "CREATE DATABASE ${empty_db}"
docker exec "${container}" psql -h 127.0.0.1 -U postgres -d "${empty_db}" \
  -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/02_schema.sql >/dev/null
docker exec "${container}" psql -h 127.0.0.1 -U postgres -d "${empty_db}" \
  -v ON_ERROR_STOP=1 -f "${forward_sql}" >/dev/null
docker exec -i "${container}" psql -h 127.0.0.1 -U postgres -d "${empty_db}" \
  -v ON_ERROR_STOP=1 < "${rollback_sql}" >/dev/null
test "$(psql_exec -d "${empty_db}" -Atqc \
  "SELECT to_regclass('public.llm_result_stream_checkpoints') IS NULL")" = "t"

psql_exec -d postgres -qc "CREATE DATABASE ${nonempty_db}"
docker exec "${container}" psql -h 127.0.0.1 -U postgres -d "${nonempty_db}" \
  -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/02_schema.sql >/dev/null
docker exec "${container}" psql -h 127.0.0.1 -U postgres -d "${nonempty_db}" \
  -v ON_ERROR_STOP=1 -f "${forward_sql}" >/dev/null
psql_exec -d "${nonempty_db}" -qc \
  "INSERT INTO llm_result_stream_checkpoints (tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id, schema_version, file_kind, file_id, file_line_number, batch_line_count, record_count, prefix_sha256) VALUES ('standalone', 'consumer-rollback', 'default', 'batch-rollback', 1, 'result', 'file-rollback', 1, 1, 1, repeat('c', 64))"
if docker exec -i "${container}" psql -h 127.0.0.1 -U postgres -d "${nonempty_db}" \
  -v ON_ERROR_STOP=1 < "${rollback_sql}" >/dev/null 2>&1; then
  echo "Non-empty checkpoint rollback unexpectedly succeeded" >&2
  exit 1
fi
test "$(psql_exec -d "${nonempty_db}" -Atqc \
  "SELECT to_regclass('public.llm_result_stream_checkpoints') IS NOT NULL")" = "t"
test "$(psql_exec -d "${nonempty_db}" -Atqc \
  "SELECT relforcerowsecurity FROM pg_class WHERE oid = 'public.llm_result_stream_checkpoints'::regclass")" = "t"

psql_exec -d postgres -qc "DROP DATABASE ${empty_db}"
psql_exec -d postgres -qc "DROP DATABASE ${nonempty_db}"
