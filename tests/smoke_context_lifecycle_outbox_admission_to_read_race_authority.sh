#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-admission-read-race-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_read_race_owner LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_read_race_runtime LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE, CREATE ON SCHEMA public TO cwl_llm_batch_outbox_read_race_owner;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_read_race_runtime;
ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO cwl_llm_batch_outbox_read_race_owner;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_read_race_runtime;
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore

runtime_dsn = "postgresql://cwl_llm_batch_outbox_read_race_runtime@127.0.0.1/postgres"
owner_dsn = "postgresql://cwl_llm_batch_outbox_read_race_owner@127.0.0.1/postgres"

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
                        "ALTER TABLE public.llm_context_lifecycle_outbox "
                        "RENAME TO llm_context_lifecycle_outbox_admitted"
                    )
                    attacker.execute(
                        "CREATE TABLE public.llm_context_lifecycle_outbox ("
                        "tenant_scope text NOT NULL, "
                        "evidence_id text NOT NULL, "
                        "event_type text NOT NULL, "
                        "tenant_scope_sha256 text NOT NULL, "
                        "subject_ref_sha256 text NOT NULL, "
                        "authority_ref_sha256 text NOT NULL, "
                        "origin_ref_sha256 text NOT NULL, "
                        "truth_status text NOT NULL, "
                        "valid_time text NOT NULL, "
                        "system_time text NOT NULL, "
                        "provenance_ref_sha256 text NOT NULL, "
                        "evidence_ref_sha256 text NOT NULL"
                        ")"
                    )
                    attacker.execute(
                        "GRANT SELECT ON public.llm_context_lifecycle_outbox "
                        "TO cwl_llm_batch_outbox_read_race_runtime"
                    )
                    attacker.execute(
                        "INSERT INTO public.llm_context_lifecycle_outbox ("
                        "tenant_scope, evidence_id, event_type, tenant_scope_sha256, "
                        "subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, "
                        "truth_status, valid_time, system_time, provenance_ref_sha256, "
                        "evidence_ref_sha256) VALUES ("
                        "'tenant-a', 'admission-read-race', 'batch.lifecycle.observed', "
                        "%s, %s, %s, %s, 'observed', "
                        "'1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', %s, %s"
                        ")",
                        ("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64),
                    )
                self._attacker_connection.commit()
                self.attack_committed = True
            except psycopg.Error as exc:
                self._attacker_connection.rollback()
                if exc.sqlstate != "55P03":
                    raise
                self.attack_blocked = True
        return row


with psycopg.connect(owner_dsn) as attacker_connection:
    with psycopg.connect(runtime_dsn) as runtime_connection:
        with runtime_connection.cursor() as raw_cursor:
            cursor = RacingCursor(raw_cursor, attacker_connection)
            loaded = store.load_in_transaction(
                cursor,
                "admission-read-race",
                for_update=False,
            )
            runtime_connection.rollback()

assert cursor.attack_attempted, "hostile relation replacement was not exercised"
assert cursor.attack_blocked, "runtime did not retain read-schema authority through SELECT"
assert not cursor.attack_committed, "hostile relation replacement committed after admission"
assert loaded is None, "runtime read from a post-admission replacement relation"
PY

bash "$(dirname "$0")/smoke_context_lifecycle_outbox_admission_to_schema_rename_race_authority.sh"
