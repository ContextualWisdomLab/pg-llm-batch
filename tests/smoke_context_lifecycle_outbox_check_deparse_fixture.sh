#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-check-deparse-${GITHUB_RUN_ID:-local}-$$"

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

constraint_deparse() {
  local constraint_name="$1"
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.regexp_replace(pg_catalog.pg_get_expr(conbin, conrelid, false), E'\\n[[:space:]]*', ' ', 'g') FROM pg_catalog.pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND conname = '${constraint_name}'" \
    | tr -d '\r'
}

canonical_payload_expr="$(constraint_deparse ck_llm_context_lifecycle_outbox_payload_canonical_v1)"
canonical_valid_time_expr="$(constraint_deparse ck_llm_context_lifecycle_outbox_valid_time_canonical_v1)"
canonical_system_time_expr="$(constraint_deparse ck_llm_context_lifecycle_outbox_system_time_canonical_v1)"
if [[ -z "${canonical_payload_expr}" || -z "${canonical_valid_time_expr}" || -z "${canonical_system_time_expr}" ]]; then
  echo "canonical lifecycle-outbox CHECK deparse is unavailable" >&2
  exit 1
fi

# Replace every canonical CHECK that uses regex operators under one shadowing search path.
# This removes the collateral deparse mismatch that a one-constraint specimen would cause:
# built-in regex operators in untouched constraints would otherwise become schema-qualified,
# letting the aggregate expression check fail for an unrelated reason.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.llm_context_lifecycle_outbox
    DROP CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1,
    DROP CONSTRAINT ck_llm_context_lifecycle_outbox_valid_time_canonical_v1,
    DROP CONSTRAINT ck_llm_context_lifecycle_outbox_system_time_canonical_v1;

CREATE FUNCTION public.cwl_llm_batch_shadow_regex(text, text)
RETURNS boolean
LANGUAGE SQL
IMMUTABLE
AS 'SELECT true';

CREATE OPERATOR public.~ (
    FUNCTION = public.cwl_llm_batch_shadow_regex,
    LEFTARG = text,
    RIGHTARG = text
);

CREATE OPERATOR public.!~ (
    FUNCTION = public.cwl_llm_batch_shadow_regex,
    LEFTARG = text,
    RIGHTARG = text
);

SET search_path = public, pg_catalog;
ALTER TABLE public.llm_context_lifecycle_outbox
    ADD CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1
    CHECK (
        tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
        AND evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
        AND event_type ~ '^[a-z][a-z0-9._:-]{0,127}$'
        AND tenant_scope_sha256 ~ '^[0-9a-f]{64}$'
        AND subject_ref_sha256 ~ '^[0-9a-f]{64}$'
        AND authority_ref_sha256 ~ '^[0-9a-f]{64}$'
        AND origin_ref_sha256 ~ '^[0-9a-f]{64}$'
        AND truth_status IN (
            'authoritative',
            'observed',
            'inferred',
            'proposed',
            'superseded',
            'rejected'
        )
        AND provenance_ref_sha256 ~ '^[0-9a-f]{64}$'
        AND evidence_ref_sha256 ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT ck_llm_context_lifecycle_outbox_valid_time_canonical_v1
    CHECK (
        valid_time ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([.]\d{6})?Z$'
        AND valid_time::timestamptz IS NOT NULL
        AND valid_time !~ '[.]000000Z$'
        AND valid_time = CASE
            WHEN valid_time ~ '[.]' THEN
                to_char(
                    valid_time::timestamptz AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                )
            ELSE
                to_char(
                    valid_time::timestamptz AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                )
        END
    ),
    ADD CONSTRAINT ck_llm_context_lifecycle_outbox_system_time_canonical_v1
    CHECK (
        system_time ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([.]\d{6})?Z$'
        AND system_time::timestamptz IS NOT NULL
        AND system_time !~ '[.]000000Z$'
        AND system_time = CASE
            WHEN system_time ~ '[.]' THEN
                to_char(
                    system_time::timestamptz AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                )
            ELSE
                to_char(
                    system_time::timestamptz AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                )
        END
    );
RESET search_path;
SQL

hostile_payload_expr="$({
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SET search_path = public, pg_catalog; SELECT pg_catalog.regexp_replace(pg_catalog.pg_get_expr(conbin, conrelid, false), E'\\n[[:space:]]*', ' ', 'g') FROM pg_catalog.pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND conname = 'ck_llm_context_lifecycle_outbox_payload_canonical_v1'"
} | tr -d '\r')"
hostile_valid_time_expr="$({
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SET search_path = public, pg_catalog; SELECT pg_catalog.regexp_replace(pg_catalog.pg_get_expr(conbin, conrelid, false), E'\\n[[:space:]]*', ' ', 'g') FROM pg_catalog.pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND conname = 'ck_llm_context_lifecycle_outbox_valid_time_canonical_v1'"
} | tr -d '\r')"
hostile_system_time_expr="$({
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SET search_path = public, pg_catalog; SELECT pg_catalog.regexp_replace(pg_catalog.pg_get_expr(conbin, conrelid, false), E'\\n[[:space:]]*', ' ', 'g') FROM pg_catalog.pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND conname = 'ck_llm_context_lifecycle_outbox_system_time_canonical_v1'"
} | tr -d '\r')"

if [[ "${hostile_payload_expr}" != "${canonical_payload_expr}" \
   || "${hostile_valid_time_expr}" != "${canonical_valid_time_expr}" \
   || "${hostile_system_time_expr}" != "${canonical_system_time_expr}" ]]; then
  printf 'payload canonical:\n%s\npayload hostile:\n%s\n' "${canonical_payload_expr}" "${hostile_payload_expr}" >&2
  printf 'valid-time canonical:\n%s\nvalid-time hostile:\n%s\n' "${canonical_valid_time_expr}" "${hostile_valid_time_expr}" >&2
  printf 'system-time canonical:\n%s\nsystem-time hostile:\n%s\n' "${canonical_system_time_expr}" "${hostile_system_time_expr}" >&2
  echo "shadow-operator fixture does not preserve the full canonical CHECK deparse set" >&2
  exit 1
fi

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import _unsafe_outbox_constraint_sql

with psycopg.connect("postgresql://postgres@127.0.0.1/postgres") as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET search_path = public, pg_catalog")
        cursor.execute(
            "SELECT " + _unsafe_outbox_constraint_sql() + " "
            "FROM pg_catalog.pg_class AS admitted_relation "
            "WHERE admitted_relation.oid = "
            "'public.llm_context_lifecycle_outbox'::pg_catalog.regclass"
        )
        assert cursor.fetchone() == (True,), (
            "runtime CHECK authority probe admitted a canonical-deparse constraint set "
            "bound to different operator objects"
        )
PY
