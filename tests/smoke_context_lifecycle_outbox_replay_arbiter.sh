#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-arbiter-${GITHUB_RUN_ID:-local}-$$"
migration="/docker-entrypoint-initdb.d/05_context_lifecycle_outbox.sql"
constraint="uq_llm_context_lifecycle_outbox_tenant_evidence"
payload_constraint="ck_llm_context_lifecycle_outbox_payload_canonical_v1"
payload_stamp="pg-llm-batch:payload-check:v1:sha256=29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a"
operational_index="idx_llm_context_lifecycle_outbox_tenant_created"

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

assert_canonical_payload_constraint() {
  local observed
  observed="$(docker exec "${container}" psql -U postgres -d postgres -AtF '|' -c "
    SELECT contype,
           convalidated,
           connoinherit,
           pg_catalog.obj_description(oid, 'pg_constraint')
    FROM pg_constraint
    WHERE conrelid = 'public.llm_context_lifecycle_outbox'::regclass
      AND conname = '${payload_constraint}';
  ")"
  test "${observed}" = "c|t|f|${payload_stamp}"
}

assert_canonical_operational_index() {
  local observed
  observed="$(docker exec "${container}" psql -U postgres -d postgres -AtF '|' -c "
    SELECT index_method.amname,
           operational_index.indisvalid,
           operational_index.indisready,
           operational_index.indislive,
           operational_index.indisunique,
           operational_index.indnkeyatts,
           operational_index.indnatts,
           operational_index.indexprs IS NULL,
           operational_index.indpred IS NULL,
           operational_index.indkey[0] = (
             SELECT attnum
             FROM pg_attribute
             WHERE attrelid = 'public.llm_context_lifecycle_outbox'::regclass
               AND attname = 'tenant_scope'
               AND NOT attisdropped
           ),
           operational_index.indkey[1] = (
             SELECT attnum
             FROM pg_attribute
             WHERE attrelid = 'public.llm_context_lifecycle_outbox'::regclass
               AND attname = 'created_at'
               AND NOT attisdropped
           )
    FROM pg_index AS operational_index
    JOIN pg_class AS index_relation
      ON index_relation.oid = operational_index.indexrelid
    JOIN pg_am AS index_method
      ON index_method.oid = index_relation.relam
    WHERE operational_index.indexrelid =
          'public.idx_llm_context_lifecycle_outbox_tenant_created'::regclass
      AND operational_index.indrelid =
          'public.llm_context_lifecycle_outbox'::regclass;
  ")"
  test "${observed}" = 'btree|t|t|t|f|2|2|t|t|t|t'
}

assert_canonical_arbiter
assert_canonical_payload_constraint
assert_canonical_operational_index

# Existing-table structural specimen: CREATE TABLE IF NOT EXISTS must not admit
# a relation whose required column contract drifted. The migration is expected
# to fail closed before attempting constraint/index repair.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ALTER COLUMN event_type DROP NOT NULL;"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null 2>&1; then
  echo "lifecycle outbox migration admitted structurally incompatible existing table" >&2
  exit 1
fi
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ALTER COLUMN event_type SET NOT NULL;"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_arbiter
assert_canonical_payload_constraint
assert_canonical_operational_index

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

# Existing-table specimen 3: older installs can have the CREATE-time event-type
# check removed and lack the canonical aggregate payload check. Reapplying migration
# must restore a validated stamped check after CREATE TABLE IF NOT EXISTS is skipped.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<SQL
ALTER TABLE public.llm_context_lifecycle_outbox
  DROP CONSTRAINT ck_llm_context_lifecycle_outbox_event_type;
ALTER TABLE public.llm_context_lifecycle_outbox
  DROP CONSTRAINT ${payload_constraint};
SQL
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_payload_constraint

# The converged canonical payload contract must reject a row that the deliberately
# removed legacy event-type check would otherwise have admitted.
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
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
  'payload-constraint-negative',
  'Context.Invalid',
  repeat('1', 64),
  repeat('2', 64),
  repeat('3', 64),
  repeat('4', 64),
  'observed',
  '2026-09-05T00:00:00Z',
  '2026-09-05T00:00:00Z',
  repeat('5', 64),
  repeat('6', 64)
);
SQL
then
  echo "canonical lifecycle payload constraint accepted invalid event_type" >&2
  exit 1
fi

# Existing-table specimen 4: CREATE INDEX IF NOT EXISTS accepts a same-name index
# even when its key order is wrong. Migration 0008 must repair the catalog shape.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 <<SQL
DROP INDEX public.${operational_index};
CREATE INDEX ${operational_index}
  ON public.llm_context_lifecycle_outbox(created_at, tenant_scope);
SQL
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_operational_index

# Current state remains idempotently re-applicable without changing any arbiter.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
assert_canonical_arbiter
assert_canonical_payload_constraint
assert_canonical_operational_index
