#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-definer-admin-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_definer_admin_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_admin_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_admin_bridge NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_definer_admin_danger NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_definer_admin_caller,
       cwl_llm_batch_outbox_definer_admin_owner,
       cwl_llm_batch_outbox_definer_admin_bridge,
       cwl_llm_batch_outbox_definer_admin_danger;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_admin_caller;
GRANT TRUNCATE ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_definer_admin_danger;
GRANT cwl_llm_batch_outbox_definer_admin_danger
    TO cwl_llm_batch_outbox_definer_admin_bridge
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT cwl_llm_batch_outbox_definer_admin_bridge
    TO cwl_llm_batch_outbox_definer_admin_owner
    WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;

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
    'tenant-a', 'definer-admin-authority-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
);

CREATE FUNCTION public.cwl_llm_batch_outbox_definer_admin_probe()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    EXECUTE 'GRANT cwl_llm_batch_outbox_definer_admin_bridge TO cwl_llm_batch_outbox_definer_admin_caller WITH INHERIT FALSE, SET TRUE';
    RETURN 'granted';
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_definer_admin_probe()
    OWNER TO cwl_llm_batch_outbox_definer_admin_owner;
REVOKE ALL ON FUNCTION public.cwl_llm_batch_outbox_definer_admin_probe() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_definer_admin_probe()
    TO cwl_llm_batch_outbox_definer_admin_caller;
SQL

delegated="$(
  docker exec "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_admin_caller -d postgres -Atqc \
    "SELECT public.cwl_llm_batch_outbox_definer_admin_probe()"
)"
if [[ "${delegated}" != "granted" ]]; then
  echo "SECURITY DEFINER ADMIN OPTION specimen did not grant the bridge role" >&2
  exit 1
fi

bridge_set="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.pg_has_role('cwl_llm_batch_outbox_definer_admin_caller', 'cwl_llm_batch_outbox_definer_admin_bridge', 'SET')"
)"
if [[ "${bridge_set}" != "t" ]]; then
  echo "SECURITY DEFINER ADMIN OPTION specimen did not create selectable bridge membership" >&2
  exit 1
fi

remaining="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_definer_admin_caller -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_definer_admin_bridge;
SET LOCAL ROLE cwl_llm_batch_outbox_definer_admin_danger;
TRUNCATE public.llm_context_lifecycle_outbox;
COMMIT;
RESET ROLE;
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
SQL
)"
if [[ "${remaining}" != "0" ]]; then
  echo "delegated SET chain did not exercise RLS-exempt TRUNCATE authority" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SET ROLE cwl_llm_batch_outbox_definer_admin_owner;
REVOKE cwl_llm_batch_outbox_definer_admin_bridge
    FROM cwl_llm_batch_outbox_definer_admin_caller;
RESET ROLE;
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
    'tenant-a', 'definer-admin-authority-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
);
SQL

post_revoke_set="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.pg_has_role('cwl_llm_batch_outbox_definer_admin_caller', 'cwl_llm_batch_outbox_definer_admin_bridge', 'SET')"
)"
if [[ "${post_revoke_set}" != "f" ]]; then
  echo "direct delegated membership was not removed before package admission" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_definer_admin_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("definer-admin-authority-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "callable SECURITY DEFINER owner with ADMIN OPTION over a SET-reachable "
        "destructive role reached lifecycle-outbox data SQL"
    )
PY
