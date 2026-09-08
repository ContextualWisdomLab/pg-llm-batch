#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-definer-chain-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_definer_chain_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_chain_outer_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_chain_inner_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_definer_chain_caller,
       cwl_llm_batch_outbox_definer_chain_outer_owner,
       cwl_llm_batch_outbox_definer_chain_inner_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_chain_caller;
GRANT TRUNCATE ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_chain_inner_owner;

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
) VALUES (
    'tenant-a', 'definer-chain-authority-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
);

CREATE FUNCTION public.cwl_llm_batch_outbox_definer_chain_inner()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    TRUNCATE TABLE public.llm_context_lifecycle_outbox;
    RETURN 'truncated';
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_chain_inner()
    OWNER TO cwl_llm_batch_outbox_definer_chain_inner_owner;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_definer_chain_inner() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_chain_inner()
    TO cwl_llm_batch_outbox_definer_chain_outer_owner;

CREATE FUNCTION public.cwl_llm_batch_outbox_definer_chain_outer()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RETURN public.cwl_llm_batch_outbox_definer_chain_inner();
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_chain_outer()
    OWNER TO cwl_llm_batch_outbox_definer_chain_outer_owner;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_definer_chain_outer() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_chain_outer()
    TO cwl_llm_batch_outbox_definer_chain_caller;
SQL

nested_result="$(
  docker exec "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_chain_caller -d postgres -Atqc \
    "SELECT public.cwl_llm_batch_outbox_definer_chain_outer()"
)"
if [[ "${nested_result}" != "truncated" ]]; then
  echo "nested SECURITY DEFINER specimen did not execute the inner definer" >&2
  exit 1
fi

remaining="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox"
)"
if [[ "${remaining}" != "0" ]]; then
  echo "nested SECURITY DEFINER specimen did not exercise RLS-exempt TRUNCATE authority" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
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
) VALUES (
    'tenant-a', 'definer-chain-authority-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
);
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_chain_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("definer-chain-authority-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime reached lifecycle-outbox data SQL despite a caller-visible SECURITY "
        "DEFINER whose owner can execute a nested definer with TRUNCATE authority"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
REVOKE EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_chain_inner()
    FROM cwl_llm_batch_outbox_definer_chain_outer_owner;
SQL

nested_execute="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_function_privilege('cwl_llm_batch_outbox_definer_chain_outer_owner', 'public.cwl_llm_batch_outbox_definer_chain_inner()', 'EXECUTE')"
)"
if [[ "${nested_execute}" != "f" ]]; then
  echo "nested SECURITY DEFINER EXECUTE authority was not removed for positive control" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_chain_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
loaded = store.load("definer-chain-authority-a")
assert loaded is not None
assert loaded.evidence_id == "definer-chain-authority-a"
PY
