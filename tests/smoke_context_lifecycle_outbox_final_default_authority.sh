#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-default-authority-${GITHUB_RUN_ID:-local}-$$"
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

# The runtime INSERT omits created_at and context_outbox_uuid, so their defaults execute
# on every new durable intent. A restore/operator can replace one after migration 0008
# was recorded as applied without changing CHECK/RLS/trigger/rule/index authority.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE FUNCTION public.pg_llm_batch_outbox_created_at_probe()
RETURNS timestamptz
LANGUAGE plpgsql
VOLATILE
AS $$
BEGIN
    RAISE EXCEPTION 'operator default rejected canonical event';
END;
$$;
ALTER TABLE public.llm_context_lifecycle_outbox
    ALTER COLUMN created_at
    SET DEFAULT public.pg_llm_batch_outbox_created_at_probe();
SQL

if docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL' \
    >/tmp/pg-llm-batch-outbox-default-write.out 2>&1; then
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
    'standalone',
    'default-authority-red',
    'batch.lifecycle.allowed',
    repeat('0', 64),
    repeat('1', 64),
    repeat('2', 64),
    repeat('3', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('4', 64),
    repeat('5', 64)
);
SQL
  cat /tmp/pg-llm-batch-outbox-default-write.out >&2
  echo "operator default did not demonstrate hidden write-time authority" >&2
  exit 1
fi
if ! grep -Fq "operator default rejected canonical event" \
  /tmp/pg-llm-batch-outbox-default-write.out; then
  cat /tmp/pg-llm-batch-outbox-default-write.out >&2
  echo "default-authority RED failed for the wrong reason" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-default.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-default.out >&2
  echo "row-admission migration admitted an operator-owned omitted-column default" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-admission-default.out; then
  cat /tmp/pg-llm-batch-outbox-admission-default.out >&2
  echo "operator-owned default failed for the wrong reason" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.llm_context_lifecycle_outbox
    ALTER COLUMN created_at SET DEFAULT pg_catalog.now();
DROP FUNCTION public.pg_llm_batch_outbox_created_at_probe();
SQL
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# tenant_scope is explicitly supplied by the package store, but the schema deliberately
# retains a canonical standalone default for direct/operator SQL compatibility. Because
# PostgreSQL evaluates any omitted-column default at INSERT time, post-convergence drift
# can still execute operator-owned code through that declared schema surface. Migration
# 0009 must verify the exact retained default instead of proving only that one exists.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE FUNCTION public.pg_llm_batch_outbox_tenant_scope_probe()
RETURNS text
LANGUAGE plpgsql
VOLATILE
AS $$
BEGIN
    RAISE EXCEPTION 'operator tenant default rejected canonical event';
END;
$$;
ALTER TABLE public.llm_context_lifecycle_outbox
    ALTER COLUMN tenant_scope
    SET DEFAULT public.pg_llm_batch_outbox_tenant_scope_probe();
SQL

if docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL' \
    >/tmp/pg-llm-batch-outbox-tenant-default-write.out 2>&1; then
INSERT INTO public.llm_context_lifecycle_outbox (
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
    'tenant-default-authority-red',
    'batch.lifecycle.allowed',
    repeat('0', 64),
    repeat('1', 64),
    repeat('2', 64),
    repeat('3', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('4', 64),
    repeat('5', 64)
);
SQL
  cat /tmp/pg-llm-batch-outbox-tenant-default-write.out >&2
  echo "operator tenant default did not demonstrate omitted-column execution authority" >&2
  exit 1
fi
if ! grep -Fq "operator tenant default rejected canonical event" \
  /tmp/pg-llm-batch-outbox-tenant-default-write.out; then
  cat /tmp/pg-llm-batch-outbox-tenant-default-write.out >&2
  echo "tenant-default-authority RED failed for the wrong reason" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-tenant-default.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-tenant-default.out >&2
  echo "row-admission migration admitted an operator-owned tenant-scope default" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-admission-tenant-default.out; then
  cat /tmp/pg-llm-batch-outbox-admission-tenant-default.out >&2
  echo "operator-owned tenant default failed for the wrong reason" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.llm_context_lifecycle_outbox
    ALTER COLUMN tenant_scope SET DEFAULT 'standalone'::pg_catalog.text;
DROP FUNCTION public.pg_llm_batch_outbox_tenant_scope_probe();
SQL
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
