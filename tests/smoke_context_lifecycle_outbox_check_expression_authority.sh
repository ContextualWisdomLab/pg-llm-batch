#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-check-expression-${GITHUB_RUN_ID:-local}-$$"
migration="/docker-entrypoint-initdb.d/06_context_lifecycle_outbox_row_admission_authority.sql"

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

# A restored or operator-modified database can retain the canonical constraint name
# while replacing its expression after migration 0008 was already recorded as applied.
# Prove that such same-name drift can reject an otherwise canonical event, then require
# the final row-admission migration to detect the expression mismatch itself.
docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE public.llm_context_lifecycle_outbox
    DROP CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1;
ALTER TABLE public.llm_context_lifecycle_outbox
    ADD CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1
    CHECK (event_type <> 'batch.lifecycle.blocked');
SQL

if docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL' \
    >/tmp/pg-llm-batch-outbox-check-expression-write.out 2>&1; then
INSERT INTO public.llm_context_lifecycle_outbox (
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
    'same-name-check-red',
    'batch.lifecycle.blocked',
    repeat('0', 64),
    repeat('1', 64),
    repeat('2', 64),
    repeat('3', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('4', 64),
    repeat('5', 64)
);
SQL
  cat /tmp/pg-llm-batch-outbox-check-expression-write.out >&2
  echo "same-name CHECK replacement did not demonstrate hidden row-admission authority" >&2
  exit 1
fi
if ! grep -Fq "ck_llm_context_lifecycle_outbox_payload_canonical_v1" \
  /tmp/pg-llm-batch-outbox-check-expression-write.out; then
  cat /tmp/pg-llm-batch-outbox-check-expression-write.out >&2
  echo "same-name CHECK RED failed for the wrong reason" >&2
  exit 1
fi

if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-check-expression-migration.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-check-expression-migration.out >&2
  echo "row-admission migration admitted same-name CHECK expression drift" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-check-expression-migration.out; then
  cat /tmp/pg-llm-batch-outbox-check-expression-migration.out >&2
  echo "same-name CHECK drift failed for the wrong reason" >&2
  exit 1
fi

# Deparse equality alone is not object-identity evidence. After the point-in-time
# migration gate has run, an operator can replace a CHECK with the same visible SQL
# while binding its regex operators to a different schema object. With that schema
# first in the caller search_path, pg_get_expr() can render the hostile operator with
# the same unqualified token as the reviewed predicate. Runtime admission must inspect
# dependency identity before tenant state or durable rows are touched.
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

CREATE ROLE cwl_llm_batch_outbox_check_runtime LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_check_runtime;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_check_runtime;

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
    'runtime-check-dependency',
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

-- The hostile regex operator makes an invalid event type pass the same-named CHECK.
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
    'runtime-check-weakened-proof',
    'NOT A CANONICAL EVENT TYPE',
    repeat('1', 64),
    repeat('2', 64),
    repeat('3', 64),
    repeat('4', 64),
    'observed',
    '1970-01-01T00:00:00Z',
    '1970-01-01T00:00:00Z',
    repeat('5', 64),
    repeat('6', 64)
);
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_check_runtime@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
with psycopg.connect(
    "postgresql://cwl_llm_batch_outbox_check_runtime@127.0.0.1/postgres"
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SET search_path = public, pg_catalog")
        try:
            store.load_in_transaction(cursor, "runtime-check-dependency")
        except ConfigError as exc:
            assert "separated forced RLS authority" in str(exc)
        else:
            raise AssertionError(
                "runtime admitted same-deparse CHECK dependency drift after migration"
            )
PY
