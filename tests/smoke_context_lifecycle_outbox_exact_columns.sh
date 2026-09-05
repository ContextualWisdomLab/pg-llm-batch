#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-columns-${GITHUB_RUN_ID:-local}-$$"
migration="/docker-entrypoint-initdb.d/05_context_lifecycle_outbox.sql"

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

# A stale/manual additive column is not part of the pg-llm-batch aggregate contract.
# Migration must fail closed rather than silently admitting an undeclared durability
# surface that could later carry data outside the package-owned schema.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ADD COLUMN undeclared_payload text;"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-columns.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-columns.out >&2
  echo "lifecycle outbox migration admitted an undeclared live column" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-columns.out; then
  cat /tmp/pg-llm-batch-outbox-columns.out >&2
  echo "lifecycle outbox migration failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox DROP COLUMN undeclared_payload;"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# Restores can also reintroduce an older package-owned CHECK under its legacy name.
# A stricter stale predicate must not survive beside the versioned aggregate CHECK,
# otherwise valid current payloads remain blocked even though migration reports success.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ADD CONSTRAINT ck_llm_context_lifecycle_outbox_event_type CHECK (event_type = 'legacy.only');"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
legacy_event_type_constraints="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT count(*) FROM pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::regclass AND conname = 'ck_llm_context_lifecycle_outbox_event_type'"
)"
if [[ "${legacy_event_type_constraints}" != "0" ]]; then
  echo "lifecycle outbox migration retained a legacy payload CHECK" >&2
  exit 1
fi
