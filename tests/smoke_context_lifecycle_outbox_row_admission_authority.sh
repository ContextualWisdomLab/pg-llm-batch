#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-admission-${GITHUB_RUN_ID:-local}-$$"
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

# An unknown CHECK can silently narrow the package-owned event grammar without
# changing columns, canonical constraints, RLS, triggers, rules, or the replay key.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ADD CONSTRAINT ck_outbox_operator_probe CHECK (event_type <> 'batch.lifecycle.blocked');"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-check.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-check.out >&2
  echo "row-admission migration admitted an unknown CHECK constraint" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-admission-check.out; then
  cat /tmp/pg-llm-batch-outbox-admission-check.out >&2
  echo "unknown CHECK constraint failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox DROP CONSTRAINT ck_outbox_operator_probe;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# A standalone UNIQUE index is not represented by pg_constraint but still changes
# INSERT acceptance. It must not become a second replay/admission arbiter.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE UNIQUE INDEX ux_outbox_operator_probe ON public.llm_context_lifecycle_outbox(event_type);'
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-index.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-index.out >&2
  echo "row-admission migration admitted an unknown UNIQUE index" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-admission-index.out; then
  cat /tmp/pg-llm-batch-outbox-admission-index.out >&2
  echo "unknown UNIQUE index failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP INDEX public.ux_outbox_operator_probe;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
