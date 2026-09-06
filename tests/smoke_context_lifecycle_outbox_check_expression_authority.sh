#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-check-expression-${GITHUB_RUN_ID:-local}-$$"
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

# A restored or operator-modified database can retain the canonical constraint name
# while replacing its expression after migration 0008 was already recorded as applied.
# Prove that such same-name drift can reject an otherwise canonical event, then require
# the final row-admission migration to detect the expression mismatch itself.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.llm_context_lifecycle_outbox
    DROP CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1;
ALTER TABLE public.llm_context_lifecycle_outbox
    ADD CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1
    CHECK (event_type <> 'batch.lifecycle.blocked');
SQL

if docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL' \
    >/tmp/pg-llm-batch-outbox-check-expression-write.out 2>&1; then
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
    'same-name-check-red',
    'batch.lifecycle.blocked',
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
  cat /tmp/pg-llm-batch-outbox-check-expression-write.out >&2
  echo "same-name CHECK replacement did not demonstrate hidden row-admission authority" >&2
  exit 1
fi
if ! grep -Fq "ck_llm_context_lifecycle_outbox_payload_canonical_v1" \
  /tmp/pg-llm-batch-outbox-check-expression-write.out; then
  cat /tmp/pg-llm-batch-outbox-check-expression-write.out >&2
  echo "same-name CHECK RED failed for the wrong reason" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-check-expression-migration.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-check-expression-migration.out >&2
  echo "row-admission migration admitted same-name CHECK expression drift" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-check-expression-migration.out; then
  cat /tmp/pg-llm-batch-outbox-check-expression-migration.out >&2
  echo "same-name CHECK drift failed for the wrong reason" >&2
  exit 1
fi
