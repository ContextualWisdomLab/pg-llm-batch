#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-definer-admin-foreign-${GITHUB_RUN_ID:-local}-$$"

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

CREATE ROLE cwl_llm_batch_outbox_definer_admin_foreign_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_admin_foreign_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_admin_foreign_bridge NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_admin_foreign_reader NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_admin_foreign_remote LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_definer_admin_foreign_caller,
       cwl_llm_batch_outbox_definer_admin_foreign_owner,
       cwl_llm_batch_outbox_definer_admin_foreign_bridge,
       cwl_llm_batch_outbox_definer_admin_foreign_reader,
       cwl_llm_batch_outbox_definer_admin_foreign_remote;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_admin_foreign_caller;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_admin_foreign_remote;

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
    'tenant-a', 'definer-admin-foreign-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'definer-admin-foreign-b', 'batch.lifecycle.observed', repeat('1', 64),
    repeat('2', 64), repeat('3', 64), repeat('4', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('5', 64), repeat('6', 64)
);

CREATE SERVER cwl_llm_batch_outbox_definer_admin_foreign_server
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host '127.0.0.1', port '5432', dbname 'postgres');
CREATE USER MAPPING FOR cwl_llm_batch_outbox_definer_admin_foreign_reader
    SERVER cwl_llm_batch_outbox_definer_admin_foreign_server
    OPTIONS (user 'cwl_llm_batch_outbox_definer_admin_foreign_remote', password_required 'false');
GRANT USAGE ON FOREIGN SERVER cwl_llm_batch_outbox_definer_admin_foreign_server
    TO cwl_llm_batch_outbox_definer_admin_foreign_reader;

CREATE FOREIGN TABLE public.cwl_llm_batch_outbox_definer_admin_foreign_source (
    tenant_scope text,
    evidence_id text
)
    SERVER cwl_llm_batch_outbox_definer_admin_foreign_server
    OPTIONS (schema_name 'public', table_name 'llm_context_lifecycle_outbox');
REVOKE ALL ON public.cwl_llm_batch_outbox_definer_admin_foreign_source FROM PUBLIC;
GRANT SELECT ON public.cwl_llm_batch_outbox_definer_admin_foreign_source
    TO cwl_llm_batch_outbox_definer_admin_foreign_reader;

GRANT cwl_llm_batch_outbox_definer_admin_foreign_reader
    TO cwl_llm_batch_outbox_definer_admin_foreign_bridge
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT cwl_llm_batch_outbox_definer_admin_foreign_bridge
    TO cwl_llm_batch_outbox_definer_admin_foreign_owner
    WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;

CREATE FUNCTION public.cwl_llm_batch_outbox_definer_admin_foreign_grant()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    EXECUTE 'GRANT cwl_llm_batch_outbox_definer_admin_foreign_bridge TO cwl_llm_batch_outbox_definer_admin_foreign_caller WITH INHERIT FALSE, SET TRUE';
    RETURN 'granted';
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_admin_foreign_grant()
    OWNER TO cwl_llm_batch_outbox_definer_admin_foreign_owner;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_definer_admin_foreign_grant() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_admin_foreign_grant()
    TO cwl_llm_batch_outbox_definer_admin_foreign_caller;
SQL

owner_direct_select="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_table_privilege('cwl_llm_batch_outbox_definer_admin_foreign_owner', 'public.cwl_llm_batch_outbox_definer_admin_foreign_source', 'SELECT')"
)"
if [[ "${owner_direct_select}" != "f" ]]; then
  echo "definer ADMIN foreign specimen unexpectedly gives the owner direct foreign SELECT" >&2
  exit 1
fi

delegated="$(
  docker exec "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_admin_foreign_caller -d postgres -Atqc \
    "SELECT public.cwl_llm_batch_outbox_definer_admin_foreign_grant()"
)"
if [[ "${delegated}" != "granted" ]]; then
  echo "definer ADMIN foreign specimen did not grant the selectable bridge" >&2
  exit 1
fi

foreign_count="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_admin_foreign_caller -d postgres -Atq \
    -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_definer_admin_foreign_bridge;
SET LOCAL ROLE cwl_llm_batch_outbox_definer_admin_foreign_reader;
SELECT pg_catalog.count(*) FROM public.cwl_llm_batch_outbox_definer_admin_foreign_source;
ROLLBACK;
SQL
)"
if [[ "${foreign_count}" != "2" ]]; then
  echo "delegated SET chain did not reproduce the remote cross-tenant read" >&2
  printf '%s\n' "${foreign_count}" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SET ROLE cwl_llm_batch_outbox_definer_admin_foreign_owner;
REVOKE cwl_llm_batch_outbox_definer_admin_foreign_bridge
    FROM cwl_llm_batch_outbox_definer_admin_foreign_caller;
RESET ROLE;
SQL

post_revoke_set="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.pg_has_role('cwl_llm_batch_outbox_definer_admin_foreign_caller', 'cwl_llm_batch_outbox_definer_admin_foreign_bridge', 'SET')"
)"
if [[ "${post_revoke_set}" != "f" ]]; then
  echo "delegated bridge membership was not removed before package admission" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_admin_foreign_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("definer-admin-foreign-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime admitted a callable SECURITY DEFINER whose owner can delegate a "
        "SET chain to a foreign-reader role with an opaque BYPASSRLS remote mapping"
    )
PY
