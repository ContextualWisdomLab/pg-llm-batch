#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-role-authority-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE pg_llm_batch_outbox_safe LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_bypass LOGIN NOSUPERUSER BYPASSRLS;
GRANT USAGE ON SCHEMA public TO pg_llm_batch_outbox_safe, pg_llm_batch_outbox_bypass;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_safe, pg_llm_batch_outbox_bypass;

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
    'tenant-a', 'role-authority-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'role-authority-b', 'batch.lifecycle.observed', repeat('6', 64),
    repeat('7', 64), repeat('8', 64), repeat('9', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('0', 64), repeat('1', 64)
);
SQL

safe_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_safe;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${safe_visible}" != "1" ]]; then
  echo "ordinary application role did not remain tenant-isolated" >&2
  exit 1
fi

bypass_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_bypass;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${bypass_visible}" != "2" ]]; then
  echo "BYPASSRLS specimen did not demonstrate the authority being rejected" >&2
  exit 1
fi

# Share the PostgreSQL network namespace so the production package talks to this
# exact database. SET ROLE proves admission follows effective CURRENT_USER rather
# than connection/DSN text; the operator connection is deliberately superuser.
docker run --rm --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://postgres@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

with psycopg.connect("postgresql://postgres@127.0.0.1/postgres") as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE pg_llm_batch_outbox_safe")
        row = store.load_in_transaction(cursor, "role-authority-a")
        assert row is not None
        assert row.evidence_id == "role-authority-a"
        cursor.execute("RESET ROLE")

        cursor.execute("SET ROLE pg_llm_batch_outbox_bypass")
        try:
            store.load_in_transaction(cursor, "role-authority-a")
        except ConfigError as exc:
            assert "NOSUPERUSER NOBYPASSRLS" in str(exc)
        else:
            raise AssertionError("BYPASSRLS effective role reached lifecycle outbox data SQL")
        cursor.execute("RESET ROLE")

        try:
            store.load_in_transaction(cursor, "role-authority-a")
        except ConfigError as exc:
            assert "NOSUPERUSER NOBYPASSRLS" in str(exc)
        else:
            raise AssertionError("superuser effective role reached lifecycle outbox data SQL")
PY
