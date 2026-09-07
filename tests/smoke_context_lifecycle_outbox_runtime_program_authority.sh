#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-runtime-program-${GITHUB_RUN_ID:-local}-$$"

cleanup() {
  docker rm --force "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

psql_stdin() {
  docker exec -i "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 "$@"
}

assert_runtime_rejected() {
  local description="$1"
  docker run --rm -i --network "container:${container}" "${component_image}" python - "${description}" <<'PY'
import sys

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

store = PostgresContextLifecycleOutboxStore(
    "postgresql://cwl_llm_batch_outbox_program_runtime@127.0.0.1/postgres",
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)
try:
    store.load("runtime-program-missing")
except ConfigError as exc:
    assert "separated forced RLS authority" in str(exc)
else:
    raise AssertionError(f"runtime admitted post-migration {sys.argv[1]} drift")
PY
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

psql_stdin <<'SQL'
CREATE ROLE cwl_llm_batch_outbox_program_owner LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_program_runtime LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_program_owner, cwl_llm_batch_outbox_program_runtime;
ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO cwl_llm_batch_outbox_program_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox TO cwl_llm_batch_outbox_program_runtime;

CREATE FUNCTION public.pg_llm_batch_outbox_runtime_trigger_probe()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.event_type = 'batch.lifecycle.blocked' THEN
        RAISE EXCEPTION 'post-migration trigger intercepted canonical write';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_outbox_runtime_program_probe
BEFORE INSERT ON public.llm_context_lifecycle_outbox
FOR EACH ROW EXECUTE FUNCTION public.pg_llm_batch_outbox_runtime_trigger_probe();
SQL

if psql_stdin <<'SQL' >/tmp/pg-llm-batch-runtime-trigger-authority.out 2>&1; then
INSERT INTO public.llm_context_lifecycle_outbox (
    tenant_scope, evidence_id, event_type, tenant_scope_sha256,
    subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, truth_status,
    valid_time, system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'tenant-a', 'runtime-program-trigger-red', 'batch.lifecycle.blocked',
    repeat('a', 64), repeat('b', 64), repeat('c', 64), repeat('d', 64),
    'observed', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z',
    repeat('e', 64), repeat('f', 64)
);
SQL
  cat /tmp/pg-llm-batch-runtime-trigger-authority.out >&2
  echo "post-migration trigger did not demonstrate executable write authority" >&2
  exit 1
fi
if ! grep -Fq "post-migration trigger intercepted canonical write" \
    /tmp/pg-llm-batch-runtime-trigger-authority.out; then
  cat /tmp/pg-llm-batch-runtime-trigger-authority.out >&2
  echo "trigger authority specimen failed for the wrong reason" >&2
  exit 1
fi
assert_runtime_rejected "user-trigger"

psql_stdin <<'SQL'
DROP TRIGGER trg_outbox_runtime_program_probe ON public.llm_context_lifecycle_outbox;
DROP FUNCTION public.pg_llm_batch_outbox_runtime_trigger_probe();
CREATE RULE rl_outbox_runtime_program_probe AS
ON INSERT TO public.llm_context_lifecycle_outbox DO INSTEAD NOTHING;
INSERT INTO public.llm_context_lifecycle_outbox (
    tenant_scope, evidence_id, event_type, tenant_scope_sha256,
    subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, truth_status,
    valid_time, system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'tenant-a', 'runtime-program-rule-red', 'batch.lifecycle.observed',
    repeat('a', 64), repeat('b', 64), repeat('c', 64), repeat('d', 64),
    'observed', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z',
    repeat('e', 64), repeat('f', 64)
);
SQL

rule_rows="$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM public.llm_context_lifecycle_outbox WHERE evidence_id = 'runtime-program-rule-red';")"
if [[ "${rule_rows}" != "0" ]]; then
  echo "post-migration rewrite rule did not demonstrate insert-suppression authority" >&2
  exit 1
fi
assert_runtime_rejected "rewrite-rule"

psql_stdin <<'SQL'
DROP RULE rl_outbox_runtime_program_probe ON public.llm_context_lifecycle_outbox;
CREATE FUNCTION public.pg_llm_batch_outbox_runtime_index_probe(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    IF value = 'batch.lifecycle.blocked' THEN
        RAISE EXCEPTION 'post-migration index expression intercepted canonical write';
    END IF;
    RETURN value;
END;
$$;
CREATE INDEX idx_llm_context_lifecycle_outbox_runtime_program_probe
ON public.llm_context_lifecycle_outbox (
    public.pg_llm_batch_outbox_runtime_index_probe(event_type)
);
REVOKE EXECUTE ON FUNCTION public.pg_llm_batch_outbox_runtime_index_probe(text) FROM PUBLIC;
SQL

if docker exec -i "${container}" psql \
    -U cwl_llm_batch_outbox_program_runtime -d postgres -v ON_ERROR_STOP=1 \
    >/tmp/pg-llm-batch-runtime-index-authority.out 2>&1 <<'SQL'; then
SET pg_llm_batch.tenant_scope = 'tenant-a';
INSERT INTO public.llm_context_lifecycle_outbox (
    tenant_scope, evidence_id, event_type, tenant_scope_sha256,
    subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, truth_status,
    valid_time, system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'tenant-a', 'runtime-program-index-red', 'batch.lifecycle.blocked',
    repeat('a', 64), repeat('b', 64), repeat('c', 64), repeat('d', 64),
    'observed', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z',
    repeat('e', 64), repeat('f', 64)
);
SQL
  cat /tmp/pg-llm-batch-runtime-index-authority.out >&2
  echo "post-migration index expression did not demonstrate executable write authority" >&2
  exit 1
fi
if ! grep -Eq \
    "post-migration index expression intercepted canonical write|permission denied for function pg_llm_batch_outbox_runtime_index_probe" \
    /tmp/pg-llm-batch-runtime-index-authority.out; then
  cat /tmp/pg-llm-batch-runtime-index-authority.out >&2
  echo "index-program authority specimen failed for the wrong reason" >&2
  exit 1
fi
assert_runtime_rejected "index-program"

psql_stdin <<'SQL'
DROP INDEX public.idx_llm_context_lifecycle_outbox_runtime_program_probe;
DROP FUNCTION public.pg_llm_batch_outbox_runtime_index_probe(text);
ALTER TABLE public.llm_context_lifecycle_outbox
    ADD CONSTRAINT ck_llm_context_lifecycle_outbox_runtime_constraint_probe
    CHECK (event_type <> 'batch.lifecycle.blocked');
SQL

if docker exec -i "${container}" psql \
    -U cwl_llm_batch_outbox_program_runtime -d postgres -v ON_ERROR_STOP=1 \
    >/tmp/pg-llm-batch-runtime-constraint-authority.out 2>&1 <<'SQL'; then
SET pg_llm_batch.tenant_scope = 'tenant-a';
INSERT INTO public.llm_context_lifecycle_outbox (
    tenant_scope, evidence_id, event_type, tenant_scope_sha256,
    subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, truth_status,
    valid_time, system_time, provenance_ref_sha256, evidence_ref_sha256
) VALUES (
    'tenant-a', 'runtime-program-constraint-red', 'batch.lifecycle.blocked',
    repeat('a', 64), repeat('b', 64), repeat('c', 64), repeat('d', 64),
    'observed', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z',
    repeat('e', 64), repeat('f', 64)
);
SQL
  cat /tmp/pg-llm-batch-runtime-constraint-authority.out >&2
  echo "post-migration CHECK did not demonstrate persistent row-admission authority" >&2
  exit 1
fi
if ! grep -Fq "ck_llm_context_lifecycle_outbox_runtime_constraint_probe" \
    /tmp/pg-llm-batch-runtime-constraint-authority.out; then
  cat /tmp/pg-llm-batch-runtime-constraint-authority.out >&2
  echo "constraint-authority specimen failed for the wrong reason" >&2
  exit 1
fi
assert_runtime_rejected "constraint"
