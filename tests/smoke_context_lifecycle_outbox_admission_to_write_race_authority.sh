#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-admission-write-race-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_race_owner LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_race_runtime LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public
    TO cwl_llm_batch_outbox_race_owner, cwl_llm_batch_outbox_race_runtime;
ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO cwl_llm_batch_outbox_race_owner;
GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_race_runtime;

CREATE FUNCTION public.pg_llm_batch_outbox_race_trigger()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'admission-to-write race trigger executed';
END;
$$;
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_evidence import ContextLifecycleEvidenceSeed
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore

runtime_dsn = "postgresql://cwl_llm_batch_outbox_race_runtime@127.0.0.1/postgres"
admin_dsn = "postgresql://postgres@127.0.0.1/postgres"

candidate = ContextLifecycleEvidenceSeed(
    evidence_id="admission-write-race",
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
)
store = PostgresContextLifecycleOutboxStore(
    runtime_dsn,
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)

class RacingCursor:
    def __init__(self, cursor, attacker_connection):
        self._cursor = cursor
        self._attacker_connection = attacker_connection
        self.attack_attempted = False
        self.attack_committed = False
        self.attack_blocked = False

    def execute(self, *args, **kwargs):
        return self._cursor.execute(*args, **kwargs)

    def fetchone(self):
        row = self._cursor.fetchone()
        if not self.attack_attempted and row == (False, False):
            self.attack_attempted = True
            try:
                with self._attacker_connection.cursor() as attacker:
                    attacker.execute("SET LOCAL lock_timeout = '500ms'")
                    attacker.execute(
                        "CREATE TRIGGER trg_outbox_admission_write_race "
                        "BEFORE INSERT ON public.llm_context_lifecycle_outbox "
                        "FOR EACH ROW EXECUTE FUNCTION "
                        "public.pg_llm_batch_outbox_race_trigger()"
                    )
                self._attacker_connection.commit()
                self.attack_committed = True
            except psycopg.Error as exc:
                self._attacker_connection.rollback()
                if exc.sqlstate != "55P03":
                    raise
                self.attack_blocked = True
        return row

with psycopg.connect(admin_dsn) as attacker_connection:
    with psycopg.connect(runtime_dsn) as runtime_connection:
        with runtime_connection.cursor() as raw_cursor:
            cursor = RacingCursor(raw_cursor, attacker_connection)
            try:
                stored = store.enqueue_in_transaction(cursor, candidate)
            except psycopg.Error as exc:
                runtime_connection.rollback()
                if cursor.attack_committed and "admission-to-write race trigger executed" in str(exc):
                    raise AssertionError(
                        "runtime admitted safe schema and then executed post-admission DDL"
                    ) from exc
                raise
            else:
                runtime_connection.rollback()

assert cursor.attack_attempted, "hostile DDL interleaving was not exercised"
assert cursor.attack_blocked, "runtime did not hold write-schema authority through INSERT"
assert not cursor.attack_committed, "hostile trigger committed between admission and INSERT"
assert stored == candidate
PY
