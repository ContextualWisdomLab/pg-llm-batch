#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-definer-invoker-scope-${GITHUB_RUN_ID:-local}-$$"

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

CREATE ROLE cwl_llm_batch_outbox_definer_invoker_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_invoker_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_definer_invoker_caller,
       cwl_llm_batch_outbox_definer_invoker_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_invoker_caller;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_invoker_owner;

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
    'tenant-a', 'definer-invoker-scope-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'definer-invoker-scope-b', 'batch.lifecycle.observed', repeat('1', 64),
    repeat('2', 64), repeat('3', 64), repeat('4', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('5', 64), repeat('6', 64)
);

CREATE FUNCTION public.cwl_llm_batch_outbox_nested_invoker_scope_read()
RETURNS text
LANGUAGE sql
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
SET pg_llm_batch.tenant_scope = 'tenant-b'
AS $$
    SELECT evidence_id
    FROM public.llm_context_lifecycle_outbox
    WHERE tenant_scope = 'tenant-b'
    ORDER BY evidence_id
    LIMIT 1
$$;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_nested_invoker_scope_read()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_nested_invoker_scope_read()
    TO cwl_llm_batch_outbox_definer_invoker_owner;

CREATE FUNCTION public.cwl_llm_batch_outbox_definer_calls_invoker_scope()
RETURNS text
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT public.cwl_llm_batch_outbox_nested_invoker_scope_read()
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_calls_invoker_scope()
    OWNER TO cwl_llm_batch_outbox_definer_invoker_owner;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_definer_calls_invoker_scope()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_calls_invoker_scope()
    TO cwl_llm_batch_outbox_definer_invoker_caller;
SQL

privilege_matrix="$(
  docker exec "${container}" psql -U postgres -d postgres -Atq -F '|' -c \
    "SELECT
       pg_catalog.has_function_privilege(
         'cwl_llm_batch_outbox_definer_invoker_caller',
         'public.cwl_llm_batch_outbox_nested_invoker_scope_read()'::pg_catalog.regprocedure,
         'EXECUTE'
       )::int,
       pg_catalog.has_function_privilege(
         'cwl_llm_batch_outbox_definer_invoker_owner',
         'public.cwl_llm_batch_outbox_nested_invoker_scope_read()'::pg_catalog.regprocedure,
         'EXECUTE'
       )::int,
       pg_catalog.has_function_privilege(
         'cwl_llm_batch_outbox_definer_invoker_caller',
         'public.cwl_llm_batch_outbox_definer_calls_invoker_scope()'::pg_catalog.regprocedure,
         'EXECUTE'
       )::int"
)"
if [[ "${privilege_matrix}" != "0|1|1" ]]; then
  echo "nested invoker specimen did not preserve caller -> definer -> invoker EXECUTE topology" >&2
  printf '%s\n' "${privilege_matrix}" >&2
  exit 1
fi

routine_matrix="$(
  docker exec "${container}" psql -U postgres -d postgres -Atq -F '|' -c \
    "SELECT
       inner_proc.prosecdef::int,
       outer_proc.prosecdef::int,
       array_to_string(inner_proc.proconfig, ','),
       array_to_string(outer_proc.proconfig, ',')
     FROM pg_catalog.pg_proc AS inner_proc
     CROSS JOIN pg_catalog.pg_proc AS outer_proc
     WHERE inner_proc.oid =
       'public.cwl_llm_batch_outbox_nested_invoker_scope_read()'::pg_catalog.regprocedure
       AND outer_proc.oid =
       'public.cwl_llm_batch_outbox_definer_calls_invoker_scope()'::pg_catalog.regprocedure"
)"
if [[ "${routine_matrix}" != 0\|1\|*"pg_llm_batch.tenant_scope=tenant-b"*\|* || \
      "${routine_matrix}" != *"search_path=pg_catalog, pg_temp"* ]]; then
  echo "nested invoker specimen did not retain invoker tenant-scope and safe outer-definer configuration" >&2
  printf '%s\n' "${routine_matrix}" >&2
  exit 1
fi

escaped="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_invoker_caller -d postgres -Atq \
    -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT public.cwl_llm_batch_outbox_definer_calls_invoker_scope();
ROLLBACK;
SQL
)"
if [[ "${escaped}" != $'tenant-a\ndefiner-invoker-scope-b' ]]; then
  echo "nested SECURITY INVOKER tenant-scope specimen did not reproduce the cross-tenant escape" >&2
  printf '%s\n' "${escaped}" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_invoker_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("definer-invoker-scope-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime admitted a caller-visible SECURITY DEFINER whose owner can execute "
        "a SECURITY INVOKER that overrides the package tenant-scope binding"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
REVOKE EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_nested_invoker_scope_read()
    FROM cwl_llm_batch_outbox_definer_invoker_owner;
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_invoker_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
loaded = store.load("definer-invoker-scope-a")
assert loaded is not None
assert loaded.evidence_id == "definer-invoker-scope-a"
PY
