#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-default-dependency-${GITHUB_RUN_ID:-local}-$$"

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

# pg_get_expr() is a presentation API whose qualification depends on search_path.
# Bind created_at to an operator-owned function with the same visible spelling as the
# PostgreSQL builtin, then prove both the semantic pg_depend edge and the textual
# deparse collision seen by a caller that explicitly puts public before pg_catalog.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE cwl_llm_batch_outbox_default_dependency_runtime
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_default_dependency_runtime;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_default_dependency_runtime;
CREATE FUNCTION public.now()
RETURNS timestamptz
LANGUAGE sql
VOLATILE
AS $$ SELECT '2001-01-01T00:00:00Z'::timestamptz $$;
SET search_path = public, pg_catalog;
ALTER TABLE public.llm_context_lifecycle_outbox
    ALTER COLUMN created_at SET DEFAULT now();
RESET search_path;
SQL

dependency_count="$({
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.count(*)
       FROM pg_catalog.pg_attrdef AS d
       JOIN pg_catalog.pg_attribute AS a
         ON a.attrelid = d.adrelid AND a.attnum = d.adnum
       JOIN pg_catalog.pg_depend AS dep
         ON dep.classid = 'pg_catalog.pg_attrdef'::pg_catalog.regclass
        AND dep.objid = d.oid
        AND dep.objsubid = 0
        AND dep.refclassid = 'pg_catalog.pg_proc'::pg_catalog.regclass
        AND dep.refobjsubid = 0
        AND dep.deptype = 'n'
      WHERE d.adrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
        AND a.attname = 'created_at'
        AND dep.refobjid = 'public.now()'::pg_catalog.regprocedure";
} | tr -d '[:space:]')"
if [[ "${dependency_count}" != "1" ]]; then
  echo "shadow default did not retain the expected public.now() dependency" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_default_dependency_runtime@127.0.0.1/postgres",
    tenant_scope="standalone",
    tenant_scope_sha256="0" * 64,
)
with psycopg.connect(
    "postgresql://cwl_llm_batch_outbox_default_dependency_runtime@127.0.0.1/postgres"
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET search_path = public, pg_catalog")
        cursor.execute(
            "SELECT pg_catalog.pg_get_expr(d.adbin, d.adrelid, false) "
            "FROM pg_catalog.pg_attrdef AS d "
            "JOIN pg_catalog.pg_attribute AS a "
            "ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
            "WHERE d.adrelid = "
            "'public.llm_context_lifecycle_outbox'::pg_catalog.regclass "
            "AND a.attname = 'created_at'"
        )
        if cursor.fetchone() != ("now()",):
            raise SystemExit(
                "shadow default did not reproduce the search_path-sensitive deparse"
            )
        try:
            store.load_in_transaction(cursor, "runtime-default-dependency-red")
        except ConfigError:
            pass
        else:
            raise SystemExit(
                "runtime admission trusted deparse text despite public.now() dependency"
            )
PY
