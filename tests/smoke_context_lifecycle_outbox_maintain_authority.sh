#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL 17 introduced table MAINTAIN. The product's default PostgreSQL 16
# image must remain supported, so this specimen intentionally uses a separate,
# digest-pinned PostgreSQL 18 image while the ordinary container suite exercises
# the version-gated admission query against PostgreSQL 16.
image="postgres:18-bookworm@sha256:33c86c9cfb790e257e470b29e8c97bd1bd6fee0a70ab2d7a2e377ab639c09935"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-maintain-${GITHUB_RUN_ID:-local}-$$"

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
      >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  docker logs "${container}" >&2 || true
  echo "digest-pinned PostgreSQL 18 image did not become ready" >&2
  exit 1
fi

server_version_num="$({
  docker exec "${container}" psql -h 127.0.0.1 -U postgres -d postgres -Atqc \
    "SHOW server_version_num"
} 2>/dev/null)"
if (( server_version_num < 170000 )); then
  echo "MAINTAIN specimen requires PostgreSQL 17 or newer" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < pg_llm_batch/migrations/0008_context_lifecycle_outbox.sql
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < pg_llm_batch/migrations/0009_context_lifecycle_outbox_row_admission_authority.sql

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE cwl_llm_batch_outbox_maintainer LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_maintainer;
GRANT SELECT, INSERT, MAINTAIN ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_maintainer;
SQL

# MAINTAIN is executable relation authority, not ordinary tenant DML. Prove the
# otherwise-minimal runtime identity can take a relation-wide ACCESS EXCLUSIVE
# lock while its row DML remains limited to SELECT/INSERT.
docker exec -i "${container}" psql -h 127.0.0.1 \
  -U cwl_llm_batch_outbox_maintainer -d postgres -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
LOCK TABLE public.llm_context_lifecycle_outbox IN ACCESS EXCLUSIVE MODE NOWAIT;
ROLLBACK;
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_maintainer@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("maintain-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with outbox MAINTAIN authority reached tenant data SQL"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
REVOKE MAINTAIN ON public.llm_context_lifecycle_outbox
    FROM cwl_llm_batch_outbox_maintainer;
SQL

# Positive control: removing only the PostgreSQL-17+ maintenance privilege restores
# the intended SELECT/INSERT application identity on the same relation and login.
docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_maintainer@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
assert store.load("maintain-authority-probe") is None
PY
