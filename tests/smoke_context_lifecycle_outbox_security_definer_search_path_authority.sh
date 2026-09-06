#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-definer-search-path-${GITHUB_RUN_ID:-local}-$$"

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

CREATE ROLE cwl_llm_batch_outbox_definer_path_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_path_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_definer_path_caller,
       cwl_llm_batch_outbox_definer_path_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_path_caller;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_path_owner;

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
    'tenant-a', 'definer-search-path-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'definer-search-path-b', 'batch.lifecycle.observed', repeat('1', 64),
    repeat('2', 64), repeat('3', 64), repeat('4', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('5', 64), repeat('6', 64)
);

CREATE TABLE public.cwl_llm_batch_outbox_definer_path_scope (
    tenant_scope text NOT NULL
);
ALTER TABLE public.cwl_llm_batch_outbox_definer_path_scope
    OWNER TO cwl_llm_batch_outbox_definer_path_owner;
INSERT INTO public.cwl_llm_batch_outbox_definer_path_scope VALUES ('tenant-a');

CREATE FUNCTION public.cwl_llm_batch_outbox_definer_path_read()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    requested_scope text;
    visible_evidence text;
BEGIN
    SELECT tenant_scope
      INTO requested_scope
      FROM cwl_llm_batch_outbox_definer_path_scope
      LIMIT 1;
    PERFORM pg_catalog.set_config(
        'pg_llm_batch.tenant_scope', requested_scope, true
    );
    SELECT evidence_id
      INTO visible_evidence
      FROM public.llm_context_lifecycle_outbox
      WHERE tenant_scope = requested_scope
      ORDER BY evidence_id
      LIMIT 1;
    RETURN visible_evidence;
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_path_read()
    OWNER TO cwl_llm_batch_outbox_definer_path_owner;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_definer_path_read() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_path_read()
    TO cwl_llm_batch_outbox_definer_path_caller;
SQL

public_create="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_schema_privilege('cwl_llm_batch_outbox_definer_path_caller', 'public', 'CREATE')"
)"
if [[ "${public_create}" != "f" ]]; then
  echo "search-path specimen unexpectedly permits caller CREATE in public" >&2
  exit 1
fi

escaped="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_path_caller -d postgres -Atq \
    -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
CREATE TEMP TABLE cwl_llm_batch_outbox_definer_path_scope (
    tenant_scope text NOT NULL
);
INSERT INTO cwl_llm_batch_outbox_definer_path_scope VALUES ('tenant-b');
SELECT public.cwl_llm_batch_outbox_definer_path_read();
ROLLBACK;
SQL
)"
if [[ "${escaped}" != "definer-search-path-b" ]]; then
  echo "unsafe SECURITY DEFINER search_path did not reproduce the temp-schema tenant escape" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_path_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("definer-search-path-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime admitted a caller-visible SECURITY DEFINER without the canonical "
        "pg_catalog, pg_temp search_path despite a reproduced cross-tenant temp-table escape"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_path_read()
    SET search_path = pg_catalog, pg_temp;
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_path_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
loaded = store.load("definer-search-path-a")
assert loaded is not None
assert loaded.evidence_id == "definer-search-path-a"
PY
