#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
container="pg-llm-batch-outbox-columns-${GITHUB_RUN_ID:-local}-$$"
migration="/docker-entrypoint-initdb.d/05_context_lifecycle_outbox.sql"

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

# Durable publication intent cannot be admitted on an UNLOGGED relation. PostgreSQL
# can preserve the same columns, constraints, RLS and indexes across SET UNLOGGED,
# while crash recovery and standby replication semantics are materially weakened.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox SET UNLOGGED;'
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-persistence.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-persistence.out >&2
  echo "lifecycle outbox migration admitted an unlogged durable relation" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-persistence.out; then
  cat /tmp/pg-llm-batch-outbox-persistence.out >&2
  echo "lifecycle outbox persistence drift failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox SET LOGGED;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# Column collation participates in text equality and unique-index semantics. Use the
# evidence identity rather than tenant_scope so the specimen changes only column/index
# authority and does not fail earlier on PostgreSQL's RLS-policy ALTER TYPE dependency.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox ALTER COLUMN evidence_id TYPE text COLLATE "C";'
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-collation.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-collation.out >&2
  echo "lifecycle outbox migration admitted noncanonical column collation" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-collation.out; then
  cat /tmp/pg-llm-batch-outbox-collation.out >&2
  echo "lifecycle outbox collation drift failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'ALTER TABLE public.llm_context_lifecycle_outbox ALTER COLUMN evidence_id TYPE text COLLATE "default";'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# A stale/manual additive column is not part of the pg-llm-batch aggregate contract.
# Migration must fail closed rather than silently admitting an undeclared durability
# surface that could later carry data outside the package-owned schema.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ADD COLUMN undeclared_payload text;"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-columns.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-columns.out >&2
  echo "lifecycle outbox migration admitted an undeclared live column" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-columns.out; then
  cat /tmp/pg-llm-batch-outbox-columns.out >&2
  echo "lifecycle outbox migration failed for the wrong reason" >&2
  exit 1
fi

# DROP COLUMN leaves a pg_attribute tombstone and physical row-layout remnant. The
# exact durable schema contract must not treat that state as equivalent to a table
# that was never extended.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox DROP COLUMN undeclared_payload;"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-dropped-column.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-dropped-column.out >&2
  echo "lifecycle outbox migration admitted a dropped-column tombstone" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-dropped-column.out; then
  cat /tmp/pg-llm-batch-outbox-dropped-column.out >&2
  echo "lifecycle outbox dropped-column drift failed for the wrong reason" >&2
  exit 1
fi

# This test-only rebuild represents explicit operator reconciliation. Production
# migration does not rewrite or silently reclaim a dropped column's physical state.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP TABLE public.llm_context_lifecycle_outbox;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# PostgreSQL parent scans recurse into inheritance children unless ONLY is used, while
# primary-key and unique constraints do not span those children. The package-owned
# durability boundary therefore rejects either side of a pg_inherits edge rather than
# silently widening replay and lifecycle reads beyond the canonical physical table.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE TABLE public.llm_context_lifecycle_outbox_shadow () INHERITS (public.llm_context_lifecycle_outbox);'
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-inheritance.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-inheritance.out >&2
  echo "lifecycle outbox migration admitted an inheritance edge" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-inheritance.out; then
  cat /tmp/pg-llm-batch-outbox-inheritance.out >&2
  echo "lifecycle outbox inheritance drift failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP TABLE public.llm_context_lifecycle_outbox_shadow;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# A user trigger is executable table authority outside the package-owned aggregate.
# Even a no-op trigger proves that arbitrary code can intercept durable INSERT/UPDATE/
# DELETE paths after migration admission. The migration must fail closed, not delete
# unknown operator code on the package's behalf.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "CREATE FUNCTION public.pg_llm_batch_outbox_trigger_probe() RETURNS trigger LANGUAGE plpgsql AS \$\$ BEGIN RETURN NEW; END \$\$; CREATE TRIGGER pg_llm_batch_outbox_trigger_probe BEFORE INSERT ON public.llm_context_lifecycle_outbox FOR EACH ROW EXECUTE FUNCTION public.pg_llm_batch_outbox_trigger_probe();"
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-trigger.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-trigger.out >&2
  echo "lifecycle outbox migration admitted an unreviewed user trigger" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-trigger.out; then
  cat /tmp/pg-llm-batch-outbox-trigger.out >&2
  echo "lifecycle outbox trigger drift failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP TRIGGER pg_llm_batch_outbox_trigger_probe ON public.llm_context_lifecycle_outbox; DROP FUNCTION public.pg_llm_batch_outbox_trigger_probe();'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# PostgreSQL rewrite rules can redirect or supplement writes before ordinary table
# execution. The canonical durable outbox owns no rule program, so any attached rule
# is structural authority drift and must require explicit operator reconciliation.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE RULE pg_llm_batch_outbox_rule_probe AS ON INSERT TO public.llm_context_lifecycle_outbox DO ALSO NOTHING;'
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/tmp/pg-llm-batch-outbox-rule.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-rule.out >&2
  echo "lifecycle outbox migration admitted an unreviewed rewrite rule" >&2
  exit 1
fi
if ! grep -Fq "lifecycle outbox structural schema mismatch" \
  /tmp/pg-llm-batch-outbox-rule.out; then
  cat /tmp/pg-llm-batch-outbox-rule.out >&2
  echo "lifecycle outbox rewrite-rule drift failed for the wrong reason" >&2
  exit 1
fi

docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'DROP RULE pg_llm_batch_outbox_rule_probe ON public.llm_context_lifecycle_outbox;'
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null

# Restores can also reintroduce an older package-owned CHECK under its legacy name.
# A stricter stale predicate must not survive beside the versioned aggregate CHECK,
# otherwise valid current payloads remain blocked even though migration reports success.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox ADD CONSTRAINT ck_llm_context_lifecycle_outbox_event_type CHECK (event_type = 'legacy.only');"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
legacy_event_type_constraints="$(
  docker exec "${container}" psql -U postgres -d postgres -Atqc \
    "SELECT count(*) FROM pg_constraint WHERE conrelid = 'public.llm_context_lifecycle_outbox'::regclass AND conname = 'ck_llm_context_lifecycle_outbox_event_type'"
)"
if [[ "${legacy_event_type_constraints}" != "0" ]]; then
  echo "lifecycle outbox migration retained a legacy payload CHECK" >&2
  exit 1
fi

# A constraint COMMENT is metadata, not executable predicate identity. Simulate a
# restore/manual drift that installs a same-name permissive CHECK and copies the
# reviewed semantic stamp. Reapplying the migration must reconstruct the canonical
# predicate rather than trusting the spoofable COMMENT alone.
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "ALTER TABLE public.llm_context_lifecycle_outbox DROP CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1; ALTER TABLE public.llm_context_lifecycle_outbox ADD CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1 CHECK (true); COMMENT ON CONSTRAINT ck_llm_context_lifecycle_outbox_payload_canonical_v1 ON public.llm_context_lifecycle_outbox IS 'pg-llm-batch:payload-check:v1:sha256=29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a';"
docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -f "${migration}" >/dev/null
if docker exec "${container}" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "INSERT INTO public.llm_context_lifecycle_outbox (tenant_scope, evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, truth_status, valid_time, system_time, provenance_ref_sha256, evidence_ref_sha256) VALUES ('tenant-a', 'stamp-spoof', 'INVALID', repeat('a', 64), repeat('b', 64), repeat('c', 64), repeat('d', 64), 'observed', '2026-09-06T00:00:00Z', '2026-09-06T00:00:00Z', repeat('e', 64), repeat('f', 64));" \
  >/tmp/pg-llm-batch-outbox-payload-spoof.out 2>&1; then
  cat /tmp/pg-llm-batch-outbox-payload-spoof.out >&2
  echo "lifecycle outbox migration trusted a spoofed canonical payload CHECK stamp" >&2
  exit 1
fi
if ! grep -Fq "ck_llm_context_lifecycle_outbox_payload_canonical_v1" \
  /tmp/pg-llm-batch-outbox-payload-spoof.out; then
  cat /tmp/pg-llm-batch-outbox-payload-spoof.out >&2
  echo "canonical payload rejection came from an unexpected constraint" >&2
  exit 1
fi
