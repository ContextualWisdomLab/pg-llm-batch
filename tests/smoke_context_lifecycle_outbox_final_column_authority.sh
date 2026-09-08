#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-final-column-authority-${GITHUB_RUN_ID:-local}-$$"
migration="/docker-entrypoint-initdb.d/06_context_lifecycle_outbox_row_admission_authority.sql"

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

# A restore/operator can remove NOT NULL after migration 0008 was recorded as applied.
# PostgreSQL CHECK constraints accept UNKNOWN, and UNIQUE permits multiple NULL keys, so
# evidence_id=NULL can otherwise bypass the canonical payload/replay-identity contract.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE cwl_llm_batch_outbox_final_column_runtime
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_final_column_runtime;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_final_column_runtime;
ALTER TABLE public.llm_context_lifecycle_outbox
    ALTER COLUMN evidence_id DROP NOT NULL;

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
    'standalone', NULL, 'batch.lifecycle.allowed',
    repeat('0', 64), repeat('1', 64), repeat('2', 64), repeat('3', 64),
    'observed', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z',
    repeat('4', 64), repeat('5', 64)
),
(
    'standalone', NULL, 'batch.lifecycle.allowed',
    repeat('0', 64), repeat('1', 64), repeat('2', 64), repeat('3', 64),
    'observed', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z',
    repeat('4', 64), repeat('5', 64)
);
SQL

null_rows="$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM public.llm_context_lifecycle_outbox WHERE evidence_id IS NULL")"
if [[ "${null_rows}" != "2" ]]; then
  echo "NOT NULL drift did not reproduce replay-identity admission failure" >&2
  exit 1
fi

# Migration 0009 already rejects this drift, but continuing runtime admission must not
# treat that earlier point-in-time verdict as transferable authority. The ordinary
# application role below has only the package's non-grantable SELECT/INSERT envelope.
docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_final_column_runtime@127.0.0.1/postgres",
    tenant_scope="standalone",
    tenant_scope_sha256="0" * 64,
)
with psycopg.connect(
    "postgresql://cwl_llm_batch_outbox_final_column_runtime@127.0.0.1/postgres"
) as connection:
    with connection.cursor() as cursor:
        try:
            store.load_in_transaction(cursor, "runtime-column-authority-red")
        except ConfigError:
            pass
        else:
            raise SystemExit(
                "runtime admission trusted migration history after live column nullability drift"
            )
PY

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-final-column.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-final-column.out >&2
  echo "row-admission migration admitted post-0008 column nullability drift" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-final-column.out; then
  cat /tmp/pg-llm-batch-outbox-final-column.out >&2
  echo "column-authority drift failed for the wrong reason" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DELETE FROM public.llm_context_lifecycle_outbox WHERE evidence_id IS NULL;
ALTER TABLE public.llm_context_lifecycle_outbox
    ALTER COLUMN evidence_id SET NOT NULL;
SQL

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
