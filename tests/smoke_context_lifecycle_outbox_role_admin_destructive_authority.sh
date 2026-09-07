#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-role-admin-destructive-${GITHUB_RUN_ID:-local}-$$"

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
    'tenant-a',
    'admin-destructive-authority-probe',
    'batch.lifecycle.observed',
    repeat('a', 64),
    repeat('b', 64),
    repeat('c', 64),
    repeat('d', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('e', 64),
    repeat('f', 64)
);

CREATE ROLE cwl_llm_batch_outbox_destructive_leaf NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_destructive_bridge NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_destructive_admin LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_destructive_leaf,
       cwl_llm_batch_outbox_destructive_bridge,
       cwl_llm_batch_outbox_destructive_admin;
GRANT TRUNCATE ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_destructive_leaf;
GRANT cwl_llm_batch_outbox_destructive_leaf
    TO cwl_llm_batch_outbox_destructive_bridge
    WITH INHERIT FALSE, SET TRUE;
GRANT cwl_llm_batch_outbox_destructive_bridge
    TO cwl_llm_batch_outbox_destructive_admin
    WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;
SQL

initial_set="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.pg_has_role('cwl_llm_batch_outbox_destructive_admin', 'cwl_llm_batch_outbox_destructive_bridge', 'SET')"
)"
if [[ "${initial_set}" != "f" ]]; then
  echo "ADMIN specimen unexpectedly began with SET authority" >&2
  exit 1
fi

admission="$(
  docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_destructive_admin@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("admin-destructive-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
    print("REJECTED")
else:
    print("ADMITTED")
PY
)"

docker exec -i "${container}" psql -h 127.0.0.1 \
  -U cwl_llm_batch_outbox_destructive_admin -d postgres -v ON_ERROR_STOP=1 <<'SQL'
GRANT cwl_llm_batch_outbox_destructive_bridge
    TO cwl_llm_batch_outbox_destructive_admin
    WITH INHERIT FALSE, SET TRUE;
SET ROLE cwl_llm_batch_outbox_destructive_leaf;
TRUNCATE TABLE public.llm_context_lifecycle_outbox;
SQL

remaining="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox"
)"
if [[ "${remaining}" != "0" ]]; then
  echo "ADMIN specimen did not materialize SET-reachable TRUNCATE authority" >&2
  exit 1
fi

if [[ "${admission}" != "REJECTED" ]]; then
  echo "runtime admitted ADMIN-delegatable SET path to destructive outbox authority" >&2
  exit 1
fi
