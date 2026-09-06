#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-admission-${GITHUB_RUN_ID:-local}-$$"
migration="/docker-entrypoint-initdb.d/06_context_lifecycle_outbox_row_admission_authority.sql"

cleanup() {
  docker rm --force "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

psql_stdin() {
  docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 "$@"
}

apply_migration() {
  docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f "${migration}" >/dev/null
}

assert_rejected() {
  local output="$1"
  local description="$2"
  if ! grep -Fq "unexpected lifecycle outbox row-admission authority" "${output}"; then
    cat "${output}" >&2
    echo "${description} failed for the wrong reason" >&2
    exit 1
  fi
}

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

# Unknown CHECK constraints can silently narrow the package-owned event grammar.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ADD CONSTRAINT ck_outbox_operator_probe CHECK (event_type <> 'batch.lifecycle.blocked');"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-check.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-check.out >&2
  echo "row-admission migration admitted an unknown CHECK constraint" >&2
  exit 1
fi
assert_rejected /tmp/pg-llm-batch-outbox-admission-check.out "unknown CHECK constraint"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox DROP CONSTRAINT ck_outbox_operator_probe;'
apply_migration

# Standalone UNIQUE indexes are independent write-admission arbiters.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE UNIQUE INDEX ux_outbox_operator_probe ON public.llm_context_lifecycle_outbox(event_type);'
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-index.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-index.out >&2
  echo "row-admission migration admitted an unknown UNIQUE index" >&2
  exit 1
fi
assert_rejected /tmp/pg-llm-batch-outbox-admission-index.out "unknown UNIQUE index"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP INDEX public.ux_outbox_operator_probe;'
apply_migration

# A non-unique expression index can execute operator-owned code for every insert.
psql_stdin <<'SQL'
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
if psql_stdin <<'SQL' >/tmp/pg-llm-batch-outbox-expression-write.out 2>&1; then
INSERT INTO public.llm_context_lifecycle_outbox (
    evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256,
    authority_ref_sha256, origin_ref_sha256, truth_status, valid_time,
    system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'expression-index-red', 'batch.lifecycle.blocked', repeat('0', 64),
    repeat('1', 64), repeat('2', 64), repeat('3', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('4', 64), repeat('5', 64)
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
assert_rejected /tmp/pg-llm-batch-outbox-admission-expression.out "executable non-unique index"
psql_stdin <<'SQL'
DROP INDEX public.ix_outbox_operator_expression_probe;
DROP FUNCTION public.pg_llm_batch_outbox_expression_probe(text);
SQL
apply_migration

# PostgreSQL-core default opclasses remain valid for ordinary non-unique indexes.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE INDEX ix_outbox_core_hash_probe ON public.llm_context_lifecycle_outbox USING hash(event_type);'
apply_migration
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP INDEX public.ix_outbox_core_hash_probe;'

# A simple column index can still execute a custom operator-class support function.
psql_stdin <<'SQL'
CREATE FUNCTION public.pg_llm_batch_outbox_text_cmp(left_value text, right_value text)
RETURNS integer
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
BEGIN
    IF left_value = 'batch.lifecycle.blocked'
       OR right_value = 'batch.lifecycle.blocked' THEN
        RAISE EXCEPTION 'operator class rejected canonical event';
    END IF;
    IF left_value < right_value THEN
        RETURN -1;
    END IF;
    IF left_value > right_value THEN
        RETURN 1;
    END IF;
    RETURN 0;
END;
$$;
CREATE OPERATOR CLASS public.pg_llm_batch_outbox_text_ops
FOR TYPE text USING btree AS
    OPERATOR 1 < (text, text),
    OPERATOR 2 <= (text, text),
    OPERATOR 3 = (text, text),
    OPERATOR 4 >= (text, text),
    OPERATOR 5 > (text, text),
    FUNCTION 1 public.pg_llm_batch_outbox_text_cmp(text, text);
CREATE INDEX ix_outbox_operator_class_probe
    ON public.llm_context_lifecycle_outbox (
        event_type public.pg_llm_batch_outbox_text_ops
    );
INSERT INTO public.llm_context_lifecycle_outbox (
    evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256,
    authority_ref_sha256, origin_ref_sha256, truth_status, valid_time,
    system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'operator-class-seed', 'batch.lifecycle.allowed', repeat('0', 64),
    repeat('1', 64), repeat('2', 64), repeat('3', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('4', 64), repeat('5', 64)
);
SQL
if psql_stdin <<'SQL' >/tmp/pg-llm-batch-outbox-opclass-write.out 2>&1; then
INSERT INTO public.llm_context_lifecycle_outbox (
    evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256,
    authority_ref_sha256, origin_ref_sha256, truth_status, valid_time,
    system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'operator-class-red', 'batch.lifecycle.blocked', repeat('0', 64),
    repeat('1', 64), repeat('2', 64), repeat('3', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('4', 64), repeat('5', 64)
);
SQL
  cat /tmp/pg-llm-batch-outbox-opclass-write.out >&2
  echo "custom operator class did not demonstrate hidden write-time authority" >&2
  exit 1
fi
if ! grep -Fq "operator class rejected canonical event" \
  /tmp/pg-llm-batch-outbox-opclass-write.out; then
  cat /tmp/pg-llm-batch-outbox-opclass-write.out >&2
  echo "operator-class RED failed for the wrong reason" >&2
  exit 1
fi
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-opclass.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-opclass.out >&2
  echo "row-admission migration admitted a custom index operator class" >&2
  exit 1
fi
assert_rejected /tmp/pg-llm-batch-outbox-admission-opclass.out "custom operator class"
psql_stdin <<'SQL'
DROP INDEX public.ix_outbox_operator_class_probe;
DROP OPERATOR CLASS public.pg_llm_batch_outbox_text_ops USING btree;
DROP FUNCTION public.pg_llm_batch_outbox_text_cmp(text, text);
DELETE FROM public.llm_context_lifecycle_outbox
WHERE evidence_id = 'operator-class-seed';
SQL
apply_migration

# Migration 0009 must re-prove no operator trigger was attached after 0008.
psql_stdin <<'SQL'
CREATE FUNCTION public.pg_llm_batch_outbox_trigger_probe()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.event_type = 'batch.lifecycle.blocked' THEN
        RAISE EXCEPTION 'operator trigger rejected canonical event';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_outbox_operator_probe
BEFORE INSERT ON public.llm_context_lifecycle_outbox
FOR EACH ROW EXECUTE FUNCTION public.pg_llm_batch_outbox_trigger_probe();
SQL
if psql_stdin <<'SQL' >/tmp/pg-llm-batch-outbox-trigger-write.out 2>&1; then
INSERT INTO public.llm_context_lifecycle_outbox (
    evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256,
    authority_ref_sha256, origin_ref_sha256, truth_status, valid_time,
    system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'trigger-program-red', 'batch.lifecycle.blocked', repeat('0', 64),
    repeat('1', 64), repeat('2', 64), repeat('3', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('4', 64), repeat('5', 64)
);
SQL
  cat /tmp/pg-llm-batch-outbox-trigger-write.out >&2
  echo "operator trigger did not demonstrate hidden write-time authority" >&2
  exit 1
fi
if ! grep -Fq "operator trigger rejected canonical event" \
  /tmp/pg-llm-batch-outbox-trigger-write.out; then
  cat /tmp/pg-llm-batch-outbox-trigger-write.out >&2
  echo "trigger-program RED failed for the wrong reason" >&2
  exit 1
fi
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-trigger.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-trigger.out >&2
  echo "row-admission migration admitted an operator trigger" >&2
  exit 1
fi
assert_rejected /tmp/pg-llm-batch-outbox-admission-trigger.out "operator trigger"
psql_stdin <<'SQL'
DROP TRIGGER trg_outbox_operator_probe ON public.llm_context_lifecycle_outbox;
DROP FUNCTION public.pg_llm_batch_outbox_trigger_probe();
SQL
apply_migration

# Rewrite rules are a second table-attached executable program surface.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE RULE rl_outbox_operator_probe AS ON INSERT TO public.llm_context_lifecycle_outbox DO INSTEAD NOTHING;'
psql_stdin <<'SQL'
INSERT INTO public.llm_context_lifecycle_outbox (
    evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256,
    authority_ref_sha256, origin_ref_sha256, truth_status, valid_time,
    system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'rewrite-program-red', 'batch.lifecycle.allowed', repeat('0', 64),
    repeat('1', 64), repeat('2', 64), repeat('3', 64), 'observed',
    '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', repeat('4', 64), repeat('5', 64)
);
SQL
if [[ "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM public.llm_context_lifecycle_outbox WHERE evidence_id = 'rewrite-program-red';")" != "0" ]]; then
  echo "operator rewrite rule did not demonstrate hidden insert authority" >&2
  exit 1
fi
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-admission-rule.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-admission-rule.out >&2
  echo "row-admission migration admitted an operator rewrite rule" >&2
  exit 1
fi
assert_rejected /tmp/pg-llm-batch-outbox-admission-rule.out "operator rewrite rule"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP RULE rl_outbox_operator_probe ON public.llm_context_lifecycle_outbox;'
apply_migration
