#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-role-authority-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE pg_llm_batch_outbox_safe LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_bypass LOGIN NOSUPERUSER BYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_owner LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_inert LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_truncate LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_delete LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_references LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE pg_llm_batch_outbox_trigger LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public
    TO pg_llm_batch_outbox_safe,
       pg_llm_batch_outbox_bypass,
       pg_llm_batch_outbox_owner,
       pg_llm_batch_outbox_inert,
       pg_llm_batch_outbox_truncate,
       pg_llm_batch_outbox_delete,
       pg_llm_batch_outbox_references,
       pg_llm_batch_outbox_trigger;
GRANT CREATE ON SCHEMA public TO pg_llm_batch_outbox_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_safe,
       pg_llm_batch_outbox_bypass,
       pg_llm_batch_outbox_inert,
       pg_llm_batch_outbox_truncate,
       pg_llm_batch_outbox_delete,
       pg_llm_batch_outbox_references,
       pg_llm_batch_outbox_trigger;
GRANT TRUNCATE ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_truncate;
GRANT DELETE ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_delete;
GRANT REFERENCES (tenant_scope, evidence_id)
    ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_references;
GRANT TRIGGER ON public.llm_context_lifecycle_outbox
    TO pg_llm_batch_outbox_trigger;

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
    'tenant-a', 'role-authority-a', 'batch.lifecycle.observed', repeat('a', 64),
    repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('e', 64), repeat('f', 64)
),
(
    'tenant-b', 'role-authority-b', 'batch.lifecycle.observed', repeat('6', 64),
    repeat('7', 64), repeat('8', 64), repeat('9', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('0', 64), repeat('1', 64)
);

ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO pg_llm_batch_outbox_owner;
GRANT pg_llm_batch_outbox_owner TO pg_llm_batch_outbox_inert
    WITH INHERIT FALSE, SET FALSE;
SQL

safe_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_safe;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${safe_visible}" != "1" ]]; then
  echo "ordinary application role did not remain tenant-isolated" >&2
  exit 1
fi

inert_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_inert;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${inert_visible}" != "1" ]]; then
  echo "inert owner-role membership unexpectedly changed tenant visibility" >&2
  exit 1
fi

inert_authority="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_inert;
SELECT pg_catalog.concat_ws(
    ',',
    pg_catalog.pg_has_role(CURRENT_USER, 'pg_llm_batch_outbox_owner', 'MEMBER'),
    pg_catalog.pg_has_role(CURRENT_USER, 'pg_llm_batch_outbox_owner', 'USAGE'),
    pg_catalog.pg_has_role(CURRENT_USER, 'pg_llm_batch_outbox_owner', 'SET'),
    pg_catalog.pg_has_role(CURRENT_USER, 'pg_llm_batch_outbox_owner', 'MEMBER WITH ADMIN OPTION')
);
ROLLBACK;
SQL
)"
if [[ "${inert_authority}" != "true,false,false,false" ]]; then
  echo "inert membership specimen did not preserve the intended PostgreSQL role semantics" >&2
  exit 1
fi

bypass_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_bypass;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${bypass_visible}" != "2" ]]; then
  echo "BYPASSRLS specimen did not demonstrate the authority being rejected" >&2
  exit 1
fi

# FORCE RLS subjects the owner while enabled, but ownership itself is schema authority:
# the owner can disable owner enforcement and immediately see both tenants. Roll back
# the mutation so production admission below observes the canonical forced-RLS state.
owner_bypass_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_owner;
ALTER TABLE public.llm_context_lifecycle_outbox NO FORCE ROW LEVEL SECURITY;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${owner_bypass_visible}" != "2" ]]; then
  echo "table-owner specimen did not demonstrate mutable RLS authority" >&2
  exit 1
fi

# PostgreSQL row security does not apply to whole-table TRUNCATE. A normal application
# identity with this table privilege can therefore destroy every tenant row while both
# relrowsecurity and relforcerowsecurity remain true. The transaction is rolled back so
# later production admission exercises the original durable rows.
truncate_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_truncate;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
TRUNCATE public.llm_context_lifecycle_outbox;
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${truncate_visible}" != "0" ]]; then
  echo "TRUNCATE specimen did not demonstrate RLS-exempt destructive authority" >&2
  exit 1
fi

# DELETE remains subject to RLS, but this outbox is append-only durability evidence.
# A normal tenant role with DELETE can erase its own committed publication intent and
# thereby turn an idempotent replay into a new first write. Prove that authority inside
# a rollback transaction, then require production admission to reject it below.
delete_remaining="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_delete;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
DELETE FROM public.llm_context_lifecycle_outbox
WHERE tenant_scope = 'tenant-a' AND evidence_id = 'role-authority-a';
RESET ROLE;
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${delete_remaining}" != "1" ]]; then
  echo "DELETE specimen did not demonstrate tenant-local durable-intent erasure" >&2
  exit 1
fi

# Column-level REFERENCES is independently grantable. Prove the role can create a
# foreign-key dependency on the canonical replay key; production admission below must
# reject that authority even though it is not a table-level REFERENCES grant.
references_created="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_references;
CREATE TEMPORARY TABLE pg_llm_batch_outbox_reference_probe (
    tenant_scope text NOT NULL,
    evidence_id text NOT NULL,
    FOREIGN KEY (tenant_scope, evidence_id)
        REFERENCES public.llm_context_lifecycle_outbox (tenant_scope, evidence_id)
) ON COMMIT DROP;
SELECT pg_catalog.count(*)
FROM pg_catalog.pg_constraint
WHERE conrelid = 'pg_temp.pg_llm_batch_outbox_reference_probe'::pg_catalog.regclass
  AND contype OPERATOR(pg_catalog.=) 'f';
ROLLBACK;
SQL
)"
if [[ "${references_created}" != "1" ]]; then
  echo "column-level REFERENCES specimen did not create the expected foreign key" >&2
  exit 1
fi

# TRIGGER is executable relation authority independent of RLS policy identity. Prove a
# normal non-owner role holding only TRIGGER plus the ordinary data privileges can
# attach a user trigger. Roll back the trigger before production admission checks run.
trigger_created="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE pg_llm_batch_outbox_trigger;
CREATE TEMPORARY TABLE pg_llm_batch_outbox_trigger_probe (probe integer) ON COMMIT DROP;
CREATE FUNCTION pg_temp.pg_llm_batch_outbox_trigger_probe()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN NEW;
END;
$$;
CREATE TRIGGER pg_llm_batch_outbox_runtime_authority_probe
BEFORE INSERT ON public.llm_context_lifecycle_outbox
FOR EACH ROW
EXECUTE FUNCTION pg_temp.pg_llm_batch_outbox_trigger_probe();
SELECT pg_catalog.count(*)
FROM pg_catalog.pg_trigger
WHERE tgrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
  AND tgname OPERATOR(pg_catalog.=) 'pg_llm_batch_outbox_runtime_authority_probe'
  AND NOT tgisinternal;
ROLLBACK;
SQL
)"
if [[ "${trigger_created}" != "1" ]]; then
  echo "TRIGGER specimen did not attach executable row-admission authority" >&2
  exit 1
fi

# Share the PostgreSQL network namespace so the production package talks to this
# exact database. SET ROLE proves admission follows effective CURRENT_USER rather
# than connection/DSN text; the operator connection is deliberately superuser.
docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://postgres@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

with psycopg.connect("postgresql://postgres@127.0.0.1/postgres") as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE pg_llm_batch_outbox_safe")
        row = store.load_in_transaction(cursor, "role-authority-a")
        assert row is not None
        assert row.evidence_id == "role-authority-a"
        cursor.execute("RESET ROLE")

        cursor.execute("SET ROLE pg_llm_batch_outbox_inert")
        row = store.load_in_transaction(cursor, "role-authority-a")
        assert row is not None
        assert row.evidence_id == "role-authority-a"
        cursor.execute("RESET ROLE")

        for unsafe_role in (
            "pg_llm_batch_outbox_truncate",
            "pg_llm_batch_outbox_delete",
            "pg_llm_batch_outbox_references",
            "pg_llm_batch_outbox_trigger",
        ):
            cursor.execute(f"SET ROLE {unsafe_role}")
            try:
                store.load_in_transaction(cursor, "role-authority-a")
            except ConfigError as exc:
                assert "separated forced RLS authority" in str(exc)
            else:
                raise AssertionError(
                    f"{unsafe_role} reached lifecycle outbox data SQL with unsafe relation authority"
                )
            cursor.execute("RESET ROLE")

        cursor.execute("SET ROLE pg_llm_batch_outbox_bypass")
        try:
            store.load_in_transaction(cursor, "role-authority-a")
        except ConfigError as exc:
            assert "separated forced RLS authority" in str(exc)
        else:
            raise AssertionError("BYPASSRLS effective role reached lifecycle outbox data SQL")
        cursor.execute("RESET ROLE")

        cursor.execute("SET ROLE pg_llm_batch_outbox_owner")
        try:
            store.load_in_transaction(cursor, "role-authority-a")
        except ConfigError as exc:
            assert "separated forced RLS authority" in str(exc)
        else:
            raise AssertionError("table-owner effective role reached lifecycle outbox data SQL")
        cursor.execute("RESET ROLE")

        try:
            store.load_in_transaction(cursor, "role-authority-a")
        except ConfigError as exc:
            assert "separated forced RLS authority" in str(exc)
        else:
            raise AssertionError("superuser effective role reached lifecycle outbox data SQL")
PY
