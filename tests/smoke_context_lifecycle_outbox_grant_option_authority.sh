#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-grant-option-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE pg_llm_batch_outbox_grantable LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_delegate LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public
    TO pg_llm_batch_outbox_grantable, pg_llm_batch_outbox_delegate;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_grantable WITH GRANT OPTION;
SQL

docker exec -i "${container}" psql -h 127.0.0.1 \
  -U pg_llm_batch_outbox_grantable -d postgres -v ON_ERROR_STOP=1 <<'SQL'
GRANT SELECT ON public.llm_context_lifecycle_outbox TO pg_llm_batch_outbox_delegate;
SQL

delegated="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_table_privilege('pg_llm_batch_outbox_delegate', 'public.llm_context_lifecycle_outbox', 'SELECT')"
)"
if [[ "${delegated}" != "t" ]]; then
  echo "SELECT WITH GRANT OPTION specimen did not delegate outbox read authority" >&2
  exit 1
fi

delegate_visible="$(
  docker exec "${container}" psql -h 127.0.0.1 \
    -U pg_llm_batch_outbox_delegate -d postgres -Atqc \
    "SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox"
)"
if [[ "${delegate_visible}" != "0" ]]; then
  echo "delegated outbox SELECT did not execute as the recipient role" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://pg_llm_batch_outbox_grantable@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("grant-option-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with outbox SELECT/INSERT grant option reached tenant data SQL"
    )
PY
