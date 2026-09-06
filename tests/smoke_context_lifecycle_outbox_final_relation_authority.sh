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

# Inheritance is a second post-convergence relation-topology authority. PostgreSQL
# parent scans can recurse into children while PK/UNIQUE constraints do not become a
# cross-hierarchy replay arbiter. A child attached after 0008 must therefore make the
# final verifier fail closed as well.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE TABLE public.llm_context_lifecycle_outbox_post_convergence_shadow () INHERITS (public.llm_context_lifecycle_outbox);'

inheritance_edges="$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM pg_inherits WHERE inhparent = 'public.llm_context_lifecycle_outbox'::regclass OR inhrelid = 'public.llm_context_lifecycle_outbox'::regclass")"
if [[ "${inheritance_edges}" == "0" ]]; then
  echo "inheritance specimen did not create relation-topology drift" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-final-inheritance.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-final-inheritance.out >&2
  echo "row-admission migration admitted post-0008 inheritance drift" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-final-inheritance.out; then
  cat /tmp/pg-llm-batch-outbox-final-inheritance.out >&2
  echo "final inheritance-authority drift failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP TABLE public.llm_context_lifecycle_outbox_post_convergence_shadow;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# Table access methods are executable storage authority. PostgreSQL permits a
# superuser/operator to register an additional table AM and ALTER an existing table to
# it after migration 0008. Reuse heap's handler here so the specimen needs no external
# extension while still proving that migration history alone cannot establish the
# currently selected access-method identity.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE ACCESS METHOD pg_llm_batch_shadow_heap TYPE TABLE HANDLER heap_tableam_handler;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox SET ACCESS METHOD pg_llm_batch_shadow_heap;'

access_method="$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT am.amname FROM pg_class AS c JOIN pg_am AS am ON am.oid = c.relam WHERE c.oid = 'public.llm_context_lifecycle_outbox'::regclass")"
if [[ "${access_method}" != "pg_llm_batch_shadow_heap" ]]; then
  echo "SET ACCESS METHOD did not reproduce relation storage-authority drift" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-final-access-method.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-final-access-method.out >&2
  echo "row-admission migration admitted post-0008 table access-method drift" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-final-access-method.out; then
  cat /tmp/pg-llm-batch-outbox-final-access-method.out >&2
  echo "final access-method drift failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox SET ACCESS METHOD heap;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP ACCESS METHOD pg_llm_batch_shadow_heap;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
