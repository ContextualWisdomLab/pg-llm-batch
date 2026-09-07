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

canonical_expr="$({
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT pg_catalog.regexp_replace(pg_catalog.pg_get_expr(conbin, conrelid, false), E'\\n[[:space:]]*', ' ', 'g') FROM pg_catalog.pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND conname = 'ck_llm_context_lifecycle_outbox_payload_canonical_v1'"
} | tr -d '\r')"
if [[ -z "${canonical_expr}" ]]; then
  echo "canonical lifecycle-outbox payload CHECK deparse is unavailable" >&2
  exit 1
fi

docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.llm_context_lifecycle_outbox
    DROP CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1;

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
    );
RESET search_path;
SQL

hostile_expr="$({
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SET search_path = public, pg_catalog; SELECT pg_catalog.regexp_replace(pg_catalog.pg_get_expr(conbin, conrelid, false), E'\\n[[:space:]]*', ' ', 'g') FROM pg_catalog.pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::pg_catalog.regclass AND conname = 'ck_llm_context_lifecycle_outbox_payload_canonical_v1'"
} | tr -d '\r')"

if [[ "${hostile_expr}" != "${canonical_expr}" ]]; then
  printf 'canonical deparse:\n%s\nhostile deparse:\n%s\n' "${canonical_expr}" "${hostile_expr}" >&2
  echo "shadow-operator fixture does not preserve the claimed CHECK deparse identity" >&2
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
            "runtime CHECK authority probe admitted a same-deparse constraint "
            "bound to a different operator object"
        )
PY
