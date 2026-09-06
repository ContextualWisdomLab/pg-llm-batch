#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-admission-${GITHUB_RUN_ID:-local}-$$"
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

# An unknown CHECK can silently narrow the package-owned event grammar without
# changing columns, canonical constraints, RLS, triggers, rules, or the replay key.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ADD CONSTRAINT ck_outbox_operator_probe CHECK (event_type <> 'batch.lifecycle.blocked');"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-check.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-check.out >&2
  echo "row-admission migration admitted an unknown CHECK constraint" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-admission-check.out; then
  cat /tmp/pg-llm-batch-outbox-admission-check.out >&2
  echo "unknown CHECK constraint failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox DROP CONSTRAINT ck_outbox_operator_probe;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# A standalone UNIQUE index is not represented by pg_constraint but still changes
# INSERT acceptance. It must not become a second replay/admission arbiter.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE UNIQUE INDEX ux_outbox_operator_probe ON public.llm_context_lifecycle_outbox(event_type);'
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-index.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-index.out >&2
  echo "row-admission migration admitted an unknown UNIQUE index" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-admission-index.out; then
  cat /tmp/pg-llm-batch-outbox-admission-index.out >&2
  echo "unknown UNIQUE index failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP INDEX public.ux_outbox_operator_probe;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# A non-unique expression index can still execute operator-owned code for every
# inserted row. PostgreSQL requires expression-index functions to be IMMUTABLE, but
# that declaration does not prove the function cannot raise and reject an otherwise
# canonical event. The authority migration must therefore reject the executable index.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE FUNCTION public.pg_llm_batch_outbox_expression_probe(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
BEGIN
    IF value = 'batch.lifecycle.blocked' THEN
        RAISE EXCEPTION 'operator expression index rejected canonical event';
    END IF;
    RETURN value;
END;
$$;
CREATE INDEX ix_outbox_operator_expression_probe
    ON public.llm_context_lifecycle_outbox (
        public.pg_llm_batch_outbox_expression_probe(event_type)
    );
SQL
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL' \
    >/tmp/pg-llm-batch-outbox-expression-write.out 2>&1; then
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
    'expression-index-red',
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
  cat /tmp/pg-llm-batch-outbox-expression-write.out >&2
  echo "operator expression index did not demonstrate hidden write-time authority" >&2
  exit 1
fi
if ! grep -Fq "operator expression index rejected canonical event" \
  /tmp/pg-llm-batch-outbox-expression-write.out; then
  cat /tmp/pg-llm-batch-outbox-expression-write.out >&2
  echo "expression-index RED failed for the wrong reason" >&2
  exit 1
fi
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-expression.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-expression.out >&2
  echo "row-admission migration admitted an executable non-unique index" >&2
  exit 1
fi
if ! grep -Fq "unexpected lifecycle outbox row-admission authority" \
  /tmp/pg-llm-batch-outbox-admission-expression.out; then
  cat /tmp/pg-llm-batch-outbox-admission-expression.out >&2
  echo "executable non-unique index failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP INDEX public.ix_outbox_operator_expression_probe;
DROP FUNCTION public.pg_llm_batch_outbox_expression_probe(text);
SQL
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
