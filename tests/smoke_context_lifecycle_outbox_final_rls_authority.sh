#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-final-rls-${GITHUB_RUN_ID:-local}-$$"
base_migration="/docker-entrypoint-initdb.d/05_context_lifecycle_outbox.sql"
authority_migration="/docker-entrypoint-initdb.d/06_context_lifecycle_outbox_row_admission_authority.sql"

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

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE pg_llm_batch_outbox_rls_probe NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT SELECT ON public.llm_context_lifecycle_outbox TO pg_llm_batch_outbox_rls_probe;

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
    'rls-final-a',
    'batch.lifecycle.observed',
    repeat('0', 64),
    repeat('1', 64),
    repeat('2', 64),
    repeat('3', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('4', 64),
    repeat('5', 64)
),
(
    'tenant-b',
    'rls-final-b',
    'batch.lifecycle.observed',
    repeat('6', 64),
    repeat('7', 64),
    repeat('8', 64),
    repeat('9', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('a', 64),
    repeat('b', 64)
);
SQL

# A restore/operator can retain the canonical policy name while replacing its
# predicates after migration 0008 was recorded as applied. Prove the drift widens
# an ordinary NOSUPERUSER/NOBYPASSRLS reader, then require migration 0009 to reject
# the catalog state instead of treating the canonical name as final authority.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP POLICY plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2
    ON public.llm_context_lifecycle_outbox;
CREATE POLICY plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2
    ON public.llm_context_lifecycle_outbox
    TO PUBLIC
    USING (true)
    WITH CHECK (true);
SQL

visible_rows="$(
  docker exec "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_rls_probe;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${visible_rows}" != "2" ]]; then
  echo "same-name drifted RLS policy did not demonstrate cross-tenant visibility" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${authority_migration}" >/tmp/pg-llm-batch-outbox-final-policy.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-final-policy.out >&2
  echo "row-admission migration admitted a same-name drifted RLS policy" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-final-policy.out; then
  cat /tmp/pg-llm-batch-outbox-final-policy.out >&2
  echo "same-name drifted RLS policy failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${base_migration}" >/dev/null
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${authority_migration}" >/dev/null

# Disabling RLS leaves the policy catalog row intact while bypassing it entirely for
# ordinary roles. Final admission must therefore prove the relation-level RLS flags,
# not merely policy presence or expression identity.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox DISABLE ROW LEVEL SECURITY;'

visible_rows="$(
  docker exec "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_rls_probe;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${visible_rows}" != "2" ]]; then
  echo "disabled RLS did not demonstrate cross-tenant visibility" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${authority_migration}" >/tmp/pg-llm-batch-outbox-final-rls.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-final-rls.out >&2
  echo "row-admission migration admitted disabled RLS" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-final-rls.out; then
  cat /tmp/pg-llm-batch-outbox-final-rls.out >&2
  echo "disabled RLS failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${base_migration}" >/dev/null
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${authority_migration}" >/dev/null
