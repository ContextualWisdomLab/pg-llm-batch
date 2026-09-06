#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-final-relation-authority-${GITHUB_RUN_ID:-local}-$$"
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

# Migration 0008 has already completed in this image. A restore/operator can later
# weaken the persistence contract without changing the table's columns, constraints,
# RLS policies, defaults, triggers/rules, or indexes. Final admission must therefore
# prove current relation durability instead of trusting migration history.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox SET UNLOGGED;'

persistence="$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT relpersistence FROM pg_class WHERE oid = 'public.llm_context_lifecycle_outbox'::regclass")"
if [[ "${persistence}" != "u" ]]; then
  echo "SET UNLOGGED did not reproduce relation durability drift" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-final-relation.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-final-relation.out >&2
  echo "row-admission migration admitted post-0008 UNLOGGED durability drift" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-final-relation.out; then
  cat /tmp/pg-llm-batch-outbox-final-relation.out >&2
  echo "final relation-authority drift failed for the wrong reason" >&2
  exit 1
fi

# Explicit test-only operator reconciliation restores logged persistence before
# final admission is attempted again. Migration 0009 itself performs no rewrite.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox SET LOGGED;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
