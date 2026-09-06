#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-session-authority-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE pg_llm_batch_outbox_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_safe NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_session_safe LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_session_escape LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_session_replication LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS REPLICATION;
CREATE ROLE pg_llm_batch_outbox_session_createdb LOGIN NOSUPERUSER CREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_session_createrole LOGIN NOSUPERUSER NOCREATEDB CREATEROLE NOBYPASSRLS;
GRANT USAGE ON SCHEMA public
    TO pg_llm_batch_outbox_owner,
       pg_llm_batch_outbox_safe,
       pg_llm_batch_outbox_session_safe,
       pg_llm_batch_outbox_session_escape,
       pg_llm_batch_outbox_session_replication,
       pg_llm_batch_outbox_session_createdb,
       pg_llm_batch_outbox_session_createrole;
ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO pg_llm_batch_outbox_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_safe,
       pg_llm_batch_outbox_session_replication,
       pg_llm_batch_outbox_session_createdb,
       pg_llm_batch_outbox_session_createrole;
GRANT pg_llm_batch_outbox_safe TO pg_llm_batch_outbox_session_safe
    WITH INHERIT FALSE, SET TRUE;
GRANT pg_llm_batch_outbox_safe TO pg_llm_batch_outbox_session_escape
    WITH INHERIT FALSE, SET TRUE;
GRANT pg_llm_batch_outbox_owner TO pg_llm_batch_outbox_session_escape
    WITH INHERIT FALSE, SET TRUE;

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
    'tenant-a',
    'session-authority-a',
    'batch.lifecycle.observed',
    repeat('a', 64),
    repeat('b', 64),
    repeat('c', 64),
    repeat('d', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('e', 64),
    repeat('f', 64)
);
SQL

escape_identity="$(
  docker exec -i "${container}" psql \
      -h 127.0.0.1 -U pg_llm_batch_outbox_session_escape -d postgres \
      -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_safe;
SELECT session_user || ',' || current_user;
ROLLBACK;
SQL
)"
if [[ "${escape_identity}" != "pg_llm_batch_outbox_session_escape,pg_llm_batch_outbox_safe" ]]; then
  echo "SET ROLE specimen did not preserve distinct authenticated/effective identities" >&2
  exit 1
fi

owner_escape="$(
  docker exec -i "${container}" psql \
      -h 127.0.0.1 -U pg_llm_batch_outbox_session_escape -d postgres \
      -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_safe;
SET LOCAL ROLE pg_llm_batch_outbox_owner;
ALTER TABLE public.llm_context_lifecycle_outbox NO FORCE ROW LEVEL SECURITY;
SELECT (NOT relforcerowsecurity)::int
FROM pg_catalog.pg_class
WHERE oid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass;
ROLLBACK;
SQL
)"
if [[ "${owner_escape}" != "1" ]]; then
  echo "authenticated login role did not demonstrate selectable owner authority" >&2
  exit 1
fi

createdb_probe="pg_llm_batch_outbox_createdb_probe_${GITHUB_RUN_ID:-local}_$$"
docker exec -i "${container}" psql \
    -h 127.0.0.1 -U pg_llm_batch_outbox_session_createdb -d postgres \
    -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${createdb_probe}\"" >/dev/null
if ! docker exec "${container}" psql -U postgres -d postgres -Atq \
    -v probe="${createdb_probe}" \
    -c "SELECT pg_catalog.count(*) FROM pg_catalog.pg_database WHERE datname = :'probe'" \
    | grep -qx '1'; then
  echo "CREATEDB specimen did not demonstrate database-administration authority" >&2
  exit 1
fi
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE \"${createdb_probe}\"" >/dev/null

docker exec -i "${container}" psql \
    -h 127.0.0.1 -U pg_llm_batch_outbox_session_createrole -d postgres \
    -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
CREATE ROLE pg_llm_batch_outbox_created_by_runtime NOLOGIN;
SQL
if ! docker exec "${container}" psql -U postgres -d postgres -Atq \
    -c "SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles WHERE rolname = 'pg_llm_batch_outbox_created_by_runtime'" \
    | grep -qx '1'; then
  echo "CREATEROLE specimen did not demonstrate role-administration authority" >&2
  exit 1
fi
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP ROLE pg_llm_batch_outbox_created_by_runtime" >/dev/null

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

safe_store = PostgresContextLifecycleOutboxStore(
    "postgresql://pg_llm_batch_outbox_session_safe@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
with psycopg.connect(
    "postgresql://pg_llm_batch_outbox_session_safe@127.0.0.1/postgres"
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE pg_llm_batch_outbox_safe")
        row = safe_store.load_in_transaction(cursor, "session-authority-a")
        assert row is not None
        assert row.evidence_id == "session-authority-a"

escape_store = PostgresContextLifecycleOutboxStore(
    "postgresql://pg_llm_batch_outbox_session_escape@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
with psycopg.connect(
    "postgresql://pg_llm_batch_outbox_session_escape@127.0.0.1/postgres"
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE pg_llm_batch_outbox_safe")
        try:
            escape_store.load_in_transaction(cursor, "session-authority-a")
        except ConfigError as exc:
            assert "separated forced RLS authority" in str(exc)
        else:
            raise AssertionError(
                "safe CURRENT_USER was admitted even though SESSION_USER can SET ROLE to owner"
            )

for administrative_role in (
    "pg_llm_batch_outbox_session_replication",
    "pg_llm_batch_outbox_session_createdb",
    "pg_llm_batch_outbox_session_createrole",
):
    store = PostgresContextLifecycleOutboxStore(
        f"postgresql://{administrative_role}@127.0.0.1/postgres",
        tenant_scope="tenant-a",
        tenant_scope_sha256="a" * 64,
    )
    with psycopg.connect(
        f"postgresql://{administrative_role}@127.0.0.1/postgres"
    ) as connection:
        with connection.cursor() as cursor:
            try:
                store.load_in_transaction(cursor, "session-authority-a")
            except ConfigError as exc:
                assert "separated forced RLS authority" in str(exc)
            else:
                raise AssertionError(
                    f"runtime login with PostgreSQL administrative authority was admitted: {administrative_role}"
                )
PY
