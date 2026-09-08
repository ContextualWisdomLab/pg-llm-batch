#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-role-admin-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_dml_group NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_role_admin LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_role_delegate LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_dml_group,
       cwl_llm_batch_outbox_role_admin,
       cwl_llm_batch_outbox_role_delegate;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_dml_group;
GRANT cwl_llm_batch_outbox_dml_group
    TO cwl_llm_batch_outbox_role_admin WITH ADMIN OPTION;
SQL

docker exec -i "${container}" psql -h 127.0.0.1 \
  -U cwl_llm_batch_outbox_role_admin -d postgres -v ON_ERROR_STOP=1 <<'SQL'
GRANT cwl_llm_batch_outbox_dml_group TO cwl_llm_batch_outbox_role_delegate;
SQL

delegated="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.has_table_privilege('cwl_llm_batch_outbox_role_delegate', 'public.llm_context_lifecycle_outbox', 'SELECT')"
)"
if [[ "${delegated}" != "t" ]]; then
  echo "role ADMIN OPTION specimen did not delegate outbox read authority" >&2
  exit 1
fi

delegate_visible="$(
  docker exec "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_role_delegate -d postgres -Atqc \
    "SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox"
)"
if [[ "${delegate_visible}" != "0" ]]; then
  echo "delegated role membership did not execute an outbox read" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_role_admin@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("role-admin-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with ADMIN OPTION over DML-bearing role reached tenant data SQL"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE cwl_llm_batch_outbox_dml_leaf NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_admin_bridge NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_transitive_admin LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_transitive_delegate LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_dml_leaf,
       cwl_llm_batch_outbox_admin_bridge,
       cwl_llm_batch_outbox_transitive_admin,
       cwl_llm_batch_outbox_transitive_delegate;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_dml_leaf,
       cwl_llm_batch_outbox_transitive_admin;
GRANT cwl_llm_batch_outbox_dml_leaf
    TO cwl_llm_batch_outbox_admin_bridge WITH INHERIT FALSE, SET TRUE;
GRANT cwl_llm_batch_outbox_admin_bridge
    TO cwl_llm_batch_outbox_transitive_admin
    WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;
SQL

docker exec -i "${container}" psql -h 127.0.0.1 \
  -U cwl_llm_batch_outbox_transitive_admin -d postgres -v ON_ERROR_STOP=1 <<'SQL'
GRANT cwl_llm_batch_outbox_admin_bridge
    TO cwl_llm_batch_outbox_transitive_delegate WITH INHERIT FALSE, SET TRUE;
SQL

transitive_visible="$(
  docker exec "${container}" psql -h 127.0.0.1 \
    -U cwl_llm_batch_outbox_transitive_delegate -d postgres -Atqc \
    "SET ROLE cwl_llm_batch_outbox_dml_leaf; SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox"
)"
if [[ "${transitive_visible}" != "0" ]]; then
  echo "role ADMIN OPTION specimen did not delegate SET-reachable outbox DML" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_transitive_admin@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("transitive-role-admin-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with ADMIN OPTION over SET-reachable DML role reached tenant data SQL"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
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
) VALUES
(
    'tenant-a', 'security-definer-authority-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'security-definer-authority-b', 'batch.lifecycle.observed', repeat('6', 64),
    repeat('7', 64), repeat('8', 64), repeat('9', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('0', 64), repeat('1', 64)
);

CREATE FUNCTION public.cwl_llm_batch_outbox_security_definer_probe()
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS 'SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox';
SQL

security_definer_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_role_delegate;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT public.cwl_llm_batch_outbox_security_definer_probe();
ROLLBACK;
SQL
)"
if [[ "${security_definer_visible}" != "2" ]]; then
  echo "SECURITY DEFINER specimen did not expose cross-tenant outbox authority" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_role_delegate@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("security-definer-authority-a")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with executable superuser SECURITY DEFINER function reached tenant data SQL"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP FUNCTION public.cwl_llm_batch_outbox_security_definer_probe();
CREATE ROLE cwl_llm_batch_outbox_truncate_definer NOLOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_truncate_definer;
GRANT TRUNCATE ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_truncate_definer;

CREATE FUNCTION public.cwl_llm_batch_outbox_truncate_definer_probe()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    TRUNCATE TABLE public.llm_context_lifecycle_outbox;
    RETURN 1;
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_truncate_definer_probe()
    OWNER TO cwl_llm_batch_outbox_truncate_definer;
SQL

truncate_definer_effect="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
      -U cwl_llm_batch_outbox_role_delegate -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SELECT public.cwl_llm_batch_outbox_truncate_definer_probe();
COMMIT;
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
SQL
)"
if [[ "${truncate_definer_effect}" != "0" ]]; then
  echo "SECURITY DEFINER specimen did not exercise delegated TRUNCATE authority" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_role_delegate@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("security-definer-truncate-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with executable TRUNCATE-bearing SECURITY DEFINER function reached tenant data SQL"
    )
PY

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP FUNCTION public.cwl_llm_batch_outbox_truncate_definer_probe();
CREATE ROLE cwl_llm_batch_outbox_createrole_definer NOLOGIN
    NOSUPERUSER NOCREATEDB CREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_createrole_definer;

CREATE FUNCTION public.cwl_llm_batch_outbox_createrole_definer_probe()
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET createrole_self_grant = 'inherit'
AS $$
BEGIN
    EXECUTE 'CREATE ROLE cwl_llm_batch_outbox_created_by_definer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS';
    RETURN 'created';
END;
$$;
ALTER FUNCTION public.cwl_llm_batch_outbox_createrole_definer_probe()
    OWNER TO cwl_llm_batch_outbox_createrole_definer;
SQL

createrole_definer_effect="$(
  docker exec -i "${container}" psql -h 127.0.0.1 \
      -U cwl_llm_batch_outbox_role_delegate -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
SELECT public.cwl_llm_batch_outbox_createrole_definer_probe();
SQL
)"
if [[ "${createrole_definer_effect}" != "created" ]]; then
  echo "SECURITY DEFINER specimen did not exercise delegated CREATEROLE authority" >&2
  exit 1
fi

created_role="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles WHERE rolname = 'cwl_llm_batch_outbox_created_by_definer'"
)"
if [[ "${created_role}" != "1" ]]; then
  echo "SECURITY DEFINER CREATEROLE specimen did not create the delegated role" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_role_delegate@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

try:
    store.load("security-definer-createrole-authority-probe")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(
        "runtime role with executable CREATEROLE-bearing SECURITY DEFINER function reached tenant data SQL"
    )
PY