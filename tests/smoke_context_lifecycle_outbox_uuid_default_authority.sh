#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-uuid-default-${GITHUB_RUN_ID:-local}-$$"
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

# Reproduce the pre-canonical package state. The repository schema provides this
# public helper for legacy tables, but lifecycle-outbox identity generation should
# converge away from mutable schema-scoped function authority to PostgreSQL core.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox ALTER COLUMN context_outbox_uuid SET DEFAULT public.uuid_generate_v4();'

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

uuid_default="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.pg_get_expr(defaults.adbin, defaults.adrelid, false) FROM pg_catalog.pg_attribute AS attribute JOIN pg_catalog.pg_attrdef AS defaults ON defaults.adrelid = attribute.attrelid AND defaults.adnum = attribute.attnum WHERE attribute.attrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND attribute.attname = 'context_outbox_uuid' AND NOT attribute.attisdropped"
)"
if [[ "${uuid_default}" != "gen_random_uuid()" ]]; then
  echo "lifecycle outbox retained non-core UUID default authority: ${uuid_default}" >&2
  exit 1
fi

# Converged installations must remain metadata-idempotent on reapplication.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
uuid_default_after_reapply="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.pg_get_expr(defaults.adbin, defaults.adrelid, false) FROM pg_catalog.pg_attribute AS attribute JOIN pg_catalog.pg_attrdef AS defaults ON defaults.adrelid = attribute.attrelid AND defaults.adnum = attribute.attnum WHERE attribute.attrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND attribute.attname = 'context_outbox_uuid' AND NOT attribute.attisdropped"
)"
if [[ "${uuid_default_after_reapply}" != "gen_random_uuid()" ]]; then
  echo "lifecycle outbox UUID default drifted after idempotent reapplication" >&2
  exit 1
fi
