#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-partitioned-foreign-${GITHUB_RUN_ID:-local}-$$"

cleanup() {
  docker rm --force "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach \
  --name "${container}" \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  "${image}" >/dev/null

ready=0
for _ in $(seq 1 60); do
  if docker exec "${container}" pg_isready -h 127.0.0.1 -U postgres -d postgres \
      >/dev/null 2>&1 && \
     docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres -Atqc \
      "SELECT (to_regclass('public.llm_context_lifecycle_outbox') IS NOT NULL)::int" \
      2>/dev/null | grep -qx '1'; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  docker logs "${container}" >&2 || true
  echo "fresh PostgreSQL image did not finish lifecycle-outbox initialization" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

CREATE ROLE cwl_llm_batch_outbox_partition_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_partition_remote LOGIN PASSWORD 'fixture-only-password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_partition_caller,
       cwl_llm_batch_outbox_partition_remote;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_partition_caller;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_partition_remote;

INSERT INTO public.llm_context_lifecycle_outbox (
    tenant_scope,
    evidence_id,
    event_type,
    tenant_scope_sha256,
    subject_ref_sha256,
    authority_ref_sha256,
    origin_ref_sha256,
    truth_status,
    valid_time,
    system_time,
    provenance_ref_sha256,
    evidence_ref_sha256
) VALUES
(
    'tenant-a', 'partitioned-foreign-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'partitioned-foreign-b', 'batch.lifecycle.observed', repeat('1', 64),
    repeat('2', 64), repeat('3', 64), repeat('4', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('5', 64), repeat('6', 64)
);

CREATE SERVER cwl_llm_batch_outbox_partition_server
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host '127.0.0.1', port '5432', dbname 'postgres');
CREATE USER MAPPING FOR cwl_llm_batch_outbox_partition_caller
    SERVER cwl_llm_batch_outbox_partition_server
    OPTIONS (user 'cwl_llm_batch_outbox_partition_remote', password_required 'false');
GRANT USAGE ON FOREIGN SERVER cwl_llm_batch_outbox_partition_server
    TO cwl_llm_batch_outbox_partition_caller;

CREATE TABLE public.cwl_llm_batch_outbox_partitioned_foreign (
    tenant_scope text,
    evidence_id text
) PARTITION BY LIST (tenant_scope);
CREATE FOREIGN TABLE public.cwl_llm_batch_outbox_partitioned_foreign_default
    PARTITION OF public.cwl_llm_batch_outbox_partitioned_foreign DEFAULT
    SERVER cwl_llm_batch_outbox_partition_server
    OPTIONS (schema_name 'public', table_name 'llm_context_lifecycle_outbox');
REVOKE ALL ON public.cwl_llm_batch_outbox_partitioned_foreign_default FROM PUBLIC;
GRANT SELECT ON public.cwl_llm_batch_outbox_partitioned_foreign
    TO cwl_llm_batch_outbox_partition_caller;
SQL

partition_privileges="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_table_privilege('cwl_llm_batch_outbox_partition_caller', 'public.cwl_llm_batch_outbox_partitioned_foreign', 'SELECT')::int || ':' || pg_catalog.has_table_privilege('cwl_llm_batch_outbox_partition_caller', 'public.cwl_llm_batch_outbox_partitioned_foreign_default', 'SELECT')::int"
)"
if [[ "${partition_privileges}" != "1:0" ]]; then
  echo "partitioned foreign specimen did not preserve parent-only SELECT authority" >&2
  printf '%s\n' "${partition_privileges}" >&2
  exit 1
fi

partition_counts="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_partition_caller -d postgres -Atq \
    -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM ONLY public.llm_context_lifecycle_outbox;
SELECT pg_catalog.count(*) FROM public.cwl_llm_batch_outbox_partitioned_foreign;
ROLLBACK;
SQL
)"
if [[ "${partition_counts}" != $'tenant-a\n1\n2' ]]; then
  echo "partitioned foreign specimen did not reproduce parent-mediated cross-tenant access" >&2
  printf '%s\n' "${partition_counts}" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_partition_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("partitioned-foreign-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime admitted a selectable partitioned parent whose foreign partition "
        "uses a BYPASSRLS remote user mapping while child SELECT remains ungranted"
    )
PY
