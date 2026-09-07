#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-definer-foreign-${GITHUB_RUN_ID:-local}-$$"

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

CREATE ROLE cwl_llm_batch_outbox_definer_foreign_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_foreign_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_foreign_remote LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_definer_foreign_caller,
       cwl_llm_batch_outbox_definer_foreign_owner,
       cwl_llm_batch_outbox_definer_foreign_remote;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_foreign_caller;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_foreign_remote;

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
    'tenant-a', 'definer-foreign-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'definer-foreign-b', 'batch.lifecycle.observed', repeat('1', 64),
    repeat('2', 64), repeat('3', 64), repeat('4', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('5', 64), repeat('6', 64)
);

CREATE SERVER cwl_llm_batch_outbox_definer_foreign_server
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host '127.0.0.1', port '5432', dbname 'postgres');
CREATE USER MAPPING FOR cwl_llm_batch_outbox_definer_foreign_owner
    SERVER cwl_llm_batch_outbox_definer_foreign_server
    OPTIONS (user 'cwl_llm_batch_outbox_definer_foreign_remote', password_required 'false');
GRANT USAGE ON FOREIGN SERVER cwl_llm_batch_outbox_definer_foreign_server
    TO cwl_llm_batch_outbox_definer_foreign_owner;

CREATE FOREIGN TABLE public.cwl_llm_batch_outbox_definer_foreign_source (
    tenant_scope text,
    evidence_id text
)
    SERVER cwl_llm_batch_outbox_definer_foreign_server
    OPTIONS (schema_name 'public', table_name 'llm_context_lifecycle_outbox');
REVOKE ALL ON public.cwl_llm_batch_outbox_definer_foreign_source FROM PUBLIC;
GRANT SELECT ON public.cwl_llm_batch_outbox_definer_foreign_source
    TO cwl_llm_batch_outbox_definer_foreign_owner;

CREATE FUNCTION public.cwl_llm_batch_outbox_definer_foreign_count()
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT pg_catalog.count(*)
    FROM public.cwl_llm_batch_outbox_definer_foreign_source
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_foreign_count()
    OWNER TO cwl_llm_batch_outbox_definer_foreign_owner;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_definer_foreign_count() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_foreign_count()
    TO cwl_llm_batch_outbox_definer_foreign_caller;
SQL

direct_foreign_select="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_table_privilege('cwl_llm_batch_outbox_definer_foreign_caller', 'public.cwl_llm_batch_outbox_definer_foreign_source', 'SELECT')"
)"
if [[ "${direct_foreign_select}" != "f" ]]; then
  echo "SECURITY DEFINER foreign specimen unexpectedly grants caller direct foreign-table SELECT" >&2
  exit 1
fi

visible_counts="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_foreign_caller -d postgres -Atq \
    -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM ONLY public.llm_context_lifecycle_outbox;
SELECT public.cwl_llm_batch_outbox_definer_foreign_count();
ROLLBACK;
SQL
)"
if [[ "${visible_counts}" != $'tenant-a\n1\n2' ]]; then
  echo "SECURITY DEFINER foreign specimen did not reproduce owner-mediated remote RLS bypass" >&2
  printf '%s\n' "${visible_counts}" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_foreign_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("definer-foreign-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime admitted a callable SECURITY DEFINER whose ordinary owner can read "
        "an opaque foreign table through an owner-specific mapping to a BYPASSRLS remote role"
    )
PY
