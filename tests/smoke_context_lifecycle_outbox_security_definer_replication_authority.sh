#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-definer-replication-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_replication_runtime LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_replication_definer NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE REPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_replication_runtime;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_replication_runtime;

CREATE FUNCTION public.cwl_llm_batch_outbox_replication_definer_probe()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    PERFORM pg_catalog.pg_create_physical_replication_slot(
        'cwl_llm_batch_outbox_replication_definer_slot'
    );
    RETURN 'created';
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_replication_definer_probe()
    OWNER TO cwl_llm_batch_outbox_replication_definer;
GRANT EXECUTE ON FUNCTION public.cwl_llm_batch_outbox_replication_definer_probe()
    TO cwl_llm_batch_outbox_replication_runtime;
SQL

runtime_replication="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT rolreplication::int FROM pg_catalog.pg_roles WHERE rolname = 'cwl_llm_batch_outbox_replication_runtime'"
)"
if [[ "${runtime_replication}" != "0" ]]; then
  echo "runtime specimen unexpectedly carries direct REPLICATION authority" >&2
  exit 1
fi

replication_definer_effect="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
      -U cwl_llm_batch_outbox_replication_runtime -d postgres -Atq \
      -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
SELECT public.cwl_llm_batch_outbox_replication_definer_probe();
SQL
)"
if [[ "${replication_definer_effect}" != "created" ]]; then
  echo "SECURITY DEFINER specimen did not exercise delegated REPLICATION authority" >&2
  exit 1
fi

created_slot="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.count(*) FROM pg_catalog.pg_replication_slots WHERE slot_name = 'cwl_llm_batch_outbox_replication_definer_slot'"
)"
if [[ "${created_slot}" != "1" ]]; then
  echo "SECURITY DEFINER REPLICATION specimen did not create the physical replication slot" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_replication_runtime@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("security-definer-replication-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with executable REPLICATION-bearing SECURITY DEFINER function reached tenant data SQL"
    )
PY
