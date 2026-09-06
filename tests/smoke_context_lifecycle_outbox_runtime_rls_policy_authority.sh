#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-runtime-policy-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_policy_owner LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_policy_runtime LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_policy_owner, cwl_llm_batch_outbox_policy_runtime;
ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO cwl_llm_batch_outbox_policy_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox TO cwl_llm_batch_outbox_policy_runtime;

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
    'tenant-a',
    'runtime-policy-a',
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
),
(
    'tenant-b',
    'runtime-policy-b',
    'batch.lifecycle.observed',
    repeat('1', 64),
    repeat('2', 64),
    repeat('3', 64),
    repeat('4', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('5', 64),
    repeat('6', 64)
);
SQL

canonical_visible="$(
  docker exec -i "${container}" psql \
      -h 127.0.0.1 -U cwl_llm_batch_outbox_policy_runtime -d postgres \
      -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${canonical_visible}" != "1" ]]; then
  echo "canonical RLS policy did not isolate the positive-control tenant" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP POLICY plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2
    ON public.llm_context_lifecycle_outbox;
CREATE POLICY plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2
    ON public.llm_context_lifecycle_outbox
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (true)
    WITH CHECK (true);
SQL

drift_visible="$(
  docker exec -i "${container}" psql \
      -h 127.0.0.1 -U cwl_llm_batch_outbox_policy_runtime -d postgres \
      -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${drift_visible}" != "2" ]]; then
  echo "same-name policy drift did not demonstrate cross-tenant RLS exposure" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_policy_runtime@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
with psycopg.connect(
    "postgresql://cwl_llm_batch_outbox_policy_runtime@127.0.0.1/postgres"
) as connection:
    with connection.cursor() as cursor:
        try:
            store.load_in_transaction(cursor, "runtime-policy-a")
        except ConfigError as exc:
            assert "separated forced RLS authority" in str(exc)
        else:
            raise AssertionError(
                "runtime admitted same-name RLS policy drift after migration"
            )
PY