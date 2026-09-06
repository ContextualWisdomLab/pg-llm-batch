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
CREATE ROLE cwl_llm_batch_outbox_safe LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_bypass LOGIN NOSUPERUSER BYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_owner LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_inert LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_truncate LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_delete LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_update LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_references LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_trigger LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_safe,
       cwl_llm_batch_outbox_bypass,
       cwl_llm_batch_outbox_owner,
       cwl_llm_batch_outbox_inert,
       cwl_llm_batch_outbox_truncate,
       cwl_llm_batch_outbox_delete,
       cwl_llm_batch_outbox_update,
       cwl_llm_batch_outbox_references,
       cwl_llm_batch_outbox_trigger;
GRANT CREATE ON SCHEMA public TO cwl_llm_batch_outbox_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_safe,
       cwl_llm_batch_outbox_bypass,
       cwl_llm_batch_outbox_inert,
       cwl_llm_batch_outbox_truncate,
       cwl_llm_batch_outbox_delete,
       cwl_llm_batch_outbox_update,
       cwl_llm_batch_outbox_references,
       cwl_llm_batch_outbox_trigger;
GRANT TRUNCATE ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_truncate;
GRANT DELETE ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_delete;
GRANT UPDATE (event_type) ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_update;
GRANT REFERENCES (tenant_scope, evidence_id)
    ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_references;
GRANT TRIGGER ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_trigger;

CREATE TABLE public.cwl_llm_batch_outbox_reference_probe (
    tenant_scope text NOT NULL,
    evidence_id text NOT NULL
);
ALTER TABLE public.cwl_llm_batch_outbox_reference_probe
    OWNER TO cwl_llm_batch_outbox_references;

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

ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO cwl_llm_batch_outbox_owner;
GRANT cwl_llm_batch_outbox_owner TO cwl_llm_batch_outbox_inert
    WITH INHERIT FALSE, SET FALSE;
SQL

safe_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_safe;
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
SET LOCAL ROLE cwl_llm_batch_outbox_inert;
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
SET LOCAL ROLE cwl_llm_batch_outbox_inert;
SELECT pg_catalog.concat_ws(
    ',',
    pg_catalog.pg_has_role(CURRENT_USER, 'cwl_llm_batch_outbox_owner', 'MEMBER'),
    pg_catalog.pg_has_role(CURRENT_USER, 'cwl_llm_batch_outbox_owner', 'USAGE'),
    pg_catalog.pg_has_role(CURRENT_USER, 'cwl_llm_batch_outbox_owner', 'SET'),
    pg_catalog.pg_has_role(CURRENT_USER, 'cwl_llm_batch_outbox_owner', 'MEMBER WITH ADMIN OPTION')
);
ROLLBACK;
SQL
)"
if [[ "${inert_authority}" != "t,f,f,f" ]]; then
  echo "inert membership specimen did not preserve the intended PostgreSQL role semantics: ${inert_authority}" >&2
  exit 1
fi

bypass_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_bypass;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
SELECT pg_catalog.count(*) FROM public.llm_context_lifecycle_outbox;
ROLLBACK;
SQL
)"
if [[ "${bypass_visible}" != "2" ]]; then
  echo "BYPASSRLS specimen did not demonstrate the authority being rejected" >&2
  exit 1
fi

owner_bypass_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_owner;
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

truncate_visible="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_truncate;
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

delete_remaining="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_delete;
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

update_event_type="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_update;
SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', 'tenant-a', true);
UPDATE public.llm_context_lifecycle_outbox
SET event_type = 'batch.lifecycle.updated'
WHERE tenant_scope = 'tenant-a' AND evidence_id = 'role-authority-a';
RESET ROLE;
SELECT event_type FROM public.llm_context_lifecycle_outbox
WHERE tenant_scope = 'tenant-a' AND evidence_id = 'role-authority-a';
ROLLBACK;
SQL
)"
if [[ "${update_event_type}" != "batch.lifecycle.updated" ]]; then
  echo "column-level UPDATE specimen did not mutate tenant-local durable intent" >&2
  exit 1
fi

references_created="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_references;
ALTER TABLE public.cwl_llm_batch_outbox_reference_probe
ADD CONSTRAINT cwl_llm_batch_outbox_reference_probe_fk
FOREIGN KEY (tenant_scope, evidence_id)
REFERENCES public.llm_context_lifecycle_outbox (tenant_scope, evidence_id);
SELECT pg_catalog.count(*)
FROM pg_catalog.pg_constraint
WHERE conrelid = 'public.cwl_llm_batch_outbox_reference_probe'::pg_catalog.regclass
  AND contype OPERATOR(pg_catalog.=) 'f';
ROLLBACK;
SQL
)"
if [[ "${references_created}" != "1" ]]; then
  echo "column-level REFERENCES specimen did not create the expected foreign key" >&2
  exit 1
fi

trigger_created="$(
  docker exec -i "${container}" psql -U postgres -d postgres -Atq -v ON_ERROR_STOP=1 <<'SQL' | tail -n 1
BEGIN;
SET LOCAL ROLE cwl_llm_batch_outbox_trigger;
CREATE TEMPORARY TABLE cwl_llm_batch_outbox_trigger_probe (probe integer) ON COMMIT DROP;
CREATE FUNCTION pg_temp.cwl_llm_batch_outbox_trigger_probe()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN NEW;
END;
$$;
CREATE TRIGGER cwl_llm_batch_outbox_runtime_authority_probe
BEFORE INSERT ON public.llm_context_lifecycle_outbox
FOR EACH ROW
EXECUTE FUNCTION pg_temp.cwl_llm_batch_outbox_trigger_probe();
SELECT pg_catalog.count(*)
FROM pg_catalog.pg_trigger
WHERE tgrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass
  AND tgname OPERATOR(pg_catalog.=) 'cwl_llm_batch_outbox_runtime_authority_probe'
  AND NOT tgisinternal;
ROLLBACK;
SQL
)"
if [[ "${trigger_created}" != "1" ]]; then
  echo "TRIGGER specimen did not attach executable row-admission authority" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_evidence import ContextLifecycleEvidenceSeed
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://postgres@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

with psycopg.connect("postgresql://postgres@127.0.0.1/postgres") as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE cwl_llm_batch_outbox_safe")
        row = store.load_in_transaction(cursor, "role-authority-a")
        assert row is not None
        assert row.evidence_id == "role-authority-a"
        inserted = store.enqueue_in_transaction(
            cursor,
            ContextLifecycleEvidenceSeed(
                evidence_id="role-authority-safe-insert",
                event_type="batch.lifecycle.observed",
                tenant_scope_sha256="a" * 64,
                subject_ref_sha256="b" * 64,
                authority_ref_sha256="c" * 64,
                origin_ref_sha256="d" * 64,
                truth_status="observed",
                valid_time="1970-01-01T00:00:00Z",
                system_time="1970-01-01T00:00:00Z",
                provenance_ref_sha256="e" * 64,
                evidence_ref_sha256="f" * 64,
            ),
        )
        assert inserted.evidence_id == "role-authority-safe-insert"
        cursor.execute("RESET ROLE")

        cursor.execute("SET ROLE cwl_llm_batch_outbox_inert")
        row = store.load_in_transaction(cursor, "role-authority-a")
        assert row is not None
        assert row.evidence_id == "role-authority-a"
        cursor.execute("RESET ROLE")

        for unsafe_role in (
            "cwl_llm_batch_outbox_truncate",
            "cwl_llm_batch_outbox_delete",
            "cwl_llm_batch_outbox_update",
            "cwl_llm_batch_outbox_references",
            "cwl_llm_batch_outbox_trigger",
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

        cursor.execute("SET ROLE cwl_llm_batch_outbox_bypass")
        try:
            store.load_in_transaction(cursor, "role-authority-a")
        except ConfigError as exc:
            assert "separated forced RLS authority" in str(exc)
        else:
            raise AssertionError("BYPASSRLS effective role reached lifecycle outbox data SQL")
        cursor.execute("RESET ROLE")

        cursor.execute("SET ROLE cwl_llm_batch_outbox_owner")
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
