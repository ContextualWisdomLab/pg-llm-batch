#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-arbiter-${GITHUB_RUN_ID:-local}-$$"
migration="/docker-entrypoint-initdb.d/05_context_lifecycle_outbox.sql"
constraint="uq_llm_context_lifecycle_outbox_tenant_evidence"
policy="plc_llm_context_lifecycle_outbox_tenant_scope_canonical_v2"

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

assert_canonical_arbiter() {
  local observed
  observed="$(docker exec "${container}" psql -U postgres -d postgres -AtF '|' -c "
    SELECT contype,
           convalidated,
           condeferrable,
           conkey = ARRAY[
             (SELECT attnum::smallint
              FROM pg_attribute
              WHERE attrelid = 'public.llm_context_lifecycle_outbox'::regclass
                AND attname = 'tenant_scope'
                AND NOT attisdropped),
             (SELECT attnum::smallint
              FROM pg_attribute
              WHERE attrelid = 'public.llm_context_lifecycle_outbox'::regclass
                AND attname = 'evidence_id'
                AND NOT attisdropped)
           ]
    FROM pg_constraint
    WHERE conrelid = 'public.llm_context_lifecycle_outbox'::regclass
      AND conname = '${constraint}';
  ")"
  test "${observed}" = 'u|t|f|t'
}

assert_canonical_policy_dependencies() {
  local dependency_count
  dependency_count="$(docker exec "${container}" psql -U postgres -d postgres -Atqc "
    SELECT count(*)
    FROM pg_depend AS policy_depend
    WHERE policy_depend.classid = 'pg_policy'::regclass
      AND policy_depend.objid = (
        SELECT oid
        FROM pg_policy
        WHERE polrelid = 'public.llm_context_lifecycle_outbox'::regclass
          AND polname = '${policy}'
      )
      AND policy_depend.refclassid IN (
        'pg_proc'::regclass,
        'pg_operator'::regclass
      );
  ")"
  test "${dependency_count}" = '0'
}

assert_canonical_arbiter
assert_canonical_policy_dependencies

# Existing-table specimen 1: the runtime replay arbiter is absent. Reapplying
# migration 0008 must install it even though CREATE TABLE IF NOT EXISTS is skipped.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox DROP CONSTRAINT ${constraint};"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_arbiter

# Existing-table specimen 2: a same-name UNIQUE exists, but its column order and
# deferrability make it noncanonical for the package's ON CONFLICT authority.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<SQL
ALTER TABLE public.llm_context_lifecycle_outbox DROP CONSTRAINT ${constraint};
ALTER TABLE public.llm_context_lifecycle_outbox
  ADD CONSTRAINT ${constraint}
  UNIQUE (evidence_id, tenant_scope) DEFERRABLE INITIALLY IMMEDIATE;
SQL
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_arbiter

# Prove the runtime conflict target is accepted by PostgreSQL after convergence,
# not merely that catalog flags look plausible. A duplicate replay remains one row.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
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
  'smoke',
  'replay-arbiter',
  'context.lifecycle.smoke',
  repeat('1', 64),
  repeat('2', 64),
  repeat('3', 64),
  repeat('4', 64),
  'observed',
  '2026-09-05T00:00:00Z',
  '2026-09-05T00:00:00Z',
  repeat('5', 64),
  repeat('6', 64)
)
ON CONFLICT (tenant_scope, evidence_id) DO NOTHING;

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
  'smoke',
  'replay-arbiter',
  'context.lifecycle.smoke',
  repeat('1', 64),
  repeat('2', 64),
  repeat('3', 64),
  repeat('4', 64),
  'observed',
  '2026-09-05T00:00:00Z',
  '2026-09-05T00:00:00Z',
  repeat('5', 64),
  repeat('6', 64)
)
ON CONFLICT (tenant_scope, evidence_id) DO NOTHING;
SQL

test "$(docker exec "${container}" psql -U postgres -d postgres -Atqc \
  "SELECT count(*) FROM public.llm_context_lifecycle_outbox WHERE tenant_scope = 'smoke' AND evidence_id = 'replay-arbiter'")" = "1"

# Current state remains idempotently re-applicable without changing the arbiter.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_arbiter
assert_canonical_policy_dependencies

# Existing-table specimen 3: a same-name policy can deparse to the expected text
# while its equality operator is bound to a caller-controlled schema object. The
# migration must inspect object dependencies rather than trusting pg_get_expr text.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<SQL
CREATE FUNCTION public.pg_llm_batch_outbox_shadow_eq(text, text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
AS 'SELECT true';

CREATE OPERATOR public.= (
  LEFTARG = text,
  RIGHTARG = text,
  FUNCTION = public.pg_llm_batch_outbox_shadow_eq
);

DROP POLICY ${policy} ON public.llm_context_lifecycle_outbox;
SET search_path = public, pg_catalog;
CREATE POLICY ${policy}
  ON public.llm_context_lifecycle_outbox
  TO PUBLIC
  USING (
    tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
  )
  WITH CHECK (
    tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)
  );
RESET search_path;
SQL

expected_policy_expression="(tenant_scope = current_setting('pg_llm_batch.tenant_scope'::text, true))"
observed_policy_expression="$(docker exec "${container}" psql -U postgres -d postgres -AtF '|' -c "
  SELECT pg_catalog.pg_get_expr(polqual, polrelid, false),
         pg_catalog.pg_get_expr(polwithcheck, polrelid, false)
  FROM pg_policy
  WHERE polrelid = 'public.llm_context_lifecycle_outbox'::regclass
    AND polname = '${policy}';
")"
test "${observed_policy_expression}" = \
  "${expected_policy_expression}|${expected_policy_expression}"

shadow_dependency_count="$(docker exec "${container}" psql -U postgres -d postgres -Atqc "
  SELECT count(*)
  FROM pg_depend AS policy_depend
  JOIN pg_operator AS operator_object
    ON policy_depend.refclassid = 'pg_operator'::regclass
   AND policy_depend.refobjid = operator_object.oid
  JOIN pg_namespace AS operator_namespace
    ON operator_namespace.oid = operator_object.oprnamespace
  WHERE policy_depend.classid = 'pg_policy'::regclass
    AND policy_depend.objid = (
      SELECT oid
      FROM pg_policy
      WHERE polrelid = 'public.llm_context_lifecycle_outbox'::regclass
        AND polname = '${policy}'
    )
    AND operator_namespace.nspname = 'public'
    AND operator_object.oprname = '=';
")"
test "${shadow_dependency_count}" -ge 1

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_policy_dependencies
