#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-materialized-view-${GITHUB_RUN_ID:-local}-$$"

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

CREATE ROLE cwl_llm_batch_outbox_matview_caller LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_matview_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_matview_outer_owner NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_matview_caller,
       cwl_llm_batch_outbox_matview_owner,
       cwl_llm_batch_outbox_matview_outer_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_matview_caller;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_matview_owner;

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
    'tenant-a', 'materialized-view-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'materialized-view-b', 'batch.lifecycle.observed', repeat('1', 64),
    repeat('2', 64), repeat('3', 64), repeat('4', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('5', 64), repeat('6', 64)
);

GRANT CREATE ON SCHEMA public TO cwl_llm_batch_outbox_matview_owner;
SET ROLE cwl_llm_batch_outbox_matview_owner;
CREATE MATERIALIZED VIEW public.cwl_llm_batch_outbox_privileged_materialized AS
    SELECT tenant_scope, evidence_id
    FROM public.llm_context_lifecycle_outbox;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM cwl_llm_batch_outbox_matview_owner;
REVOKE ALL ON public.cwl_llm_batch_outbox_privileged_materialized FROM PUBLIC;
GRANT SELECT ON public.cwl_llm_batch_outbox_privileged_materialized
    TO cwl_llm_batch_outbox_matview_caller;
SQL

materialized_counts="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_matview_caller -d postgres -Atq \
    -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM ONLY public.llm_context_lifecycle_outbox;
SELECT pg_catalog.count(*) FROM public.cwl_llm_batch_outbox_privileged_materialized;
ROLLBACK;
SQL
)"
if [[ "${materialized_counts}" != $'tenant-a\n1\n2' ]]; then
  echo "materialized-view specimen did not reproduce the copied cross-tenant RLS escape" >&2
  printf '%s\n' "${materialized_counts}" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_matview_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("materialized-view-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime admitted a directly selectable materialized copy derived from the "
        "forced-RLS lifecycle outbox under BYPASSRLS authority"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
REVOKE SELECT ON public.cwl_llm_batch_outbox_privileged_materialized
    FROM cwl_llm_batch_outbox_matview_caller;
GRANT CREATE ON SCHEMA public TO cwl_llm_batch_outbox_matview_outer_owner;
GRANT SELECT ON public.cwl_llm_batch_outbox_privileged_materialized
    TO cwl_llm_batch_outbox_matview_outer_owner;
SET ROLE cwl_llm_batch_outbox_matview_outer_owner;
CREATE VIEW public.cwl_llm_batch_outbox_materialized_outer AS
    SELECT tenant_scope, evidence_id
    FROM public.cwl_llm_batch_outbox_privileged_materialized;
RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM cwl_llm_batch_outbox_matview_outer_owner;
REVOKE ALL ON public.cwl_llm_batch_outbox_materialized_outer FROM PUBLIC;
GRANT SELECT ON public.cwl_llm_batch_outbox_materialized_outer
    TO cwl_llm_batch_outbox_matview_caller;
SQL

nested_direct_select="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_table_privilege('cwl_llm_batch_outbox_matview_caller', 'public.cwl_llm_batch_outbox_privileged_materialized', 'SELECT')"
)"
if [[ "${nested_direct_select}" != "f" ]]; then
  echo "nested materialized-view specimen unexpectedly grants caller direct SELECT" >&2
  exit 1
fi

nested_materialized_count="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_matview_caller -d postgres -Atq \
    -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.cwl_llm_batch_outbox_materialized_outer;
ROLLBACK;
SQL
)"
if [[ "${nested_materialized_count}" != $'tenant-a\n2' ]]; then
  echo "nested materialized-view specimen did not reproduce the indirect copied-data escape" >&2
  printf '%s\n' "${nested_materialized_count}" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_matview_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("materialized-view-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime admitted an outer view that exposes a hidden materialized copy of "
        "cross-tenant lifecycle outbox rows"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
REVOKE SELECT ON public.cwl_llm_batch_outbox_materialized_outer
    FROM cwl_llm_batch_outbox_matview_caller;
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_matview_caller@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
loaded = store.load("materialized-view-a")
assert loaded is not None
assert loaded.evidence_id == "materialized-view-a"
PY
