#!/usr/bin/env bash
set -euo pipefail

image="pg-llm-batch-postgres:ci"
component_image="pg-llm-batch:ci"
container="pg-llm-batch-outbox-admission-schema-race-${GITHUB_RUN_ID:-local}-$$"

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
CREATE ROLE cwl_llm_batch_outbox_schema_race_owner LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cwl_llm_batch_outbox_schema_race_runtime LOGIN NOSUPERUSER NOBYPASSRLS;
GRANT CREATE ON DATABASE postgres TO cwl_llm_batch_outbox_schema_race_owner;
ALTER SCHEMA public OWNER TO cwl_llm_batch_outbox_schema_race_owner;
GRANT USAGE ON SCHEMA public TO cwl_llm_batch_outbox_schema_race_runtime;
ALTER TABLE public.llm_context_lifecycle_outbox OWNER TO cwl_llm_batch_outbox_schema_race_owner;
GRANT SELECT ON public.llm_context_lifecycle_outbox
    TO cwl_llm_batch_outbox_schema_race_runtime;
SQL

docker run --rm -i --network "container:${container}" "${component_image}" python - <<'PY'
import psycopg

from pg_llm_batch.context_lifecycle_evidence import ContextLifecycleEvidenceSeed
from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError

runtime_dsn = "postgresql://cwl_llm_batch_outbox_schema_race_runtime@127.0.0.1/postgres"
owner_dsn = "postgresql://cwl_llm_batch_outbox_schema_race_owner@127.0.0.1/postgres"

store = PostgresContextLifecycleOutboxStore(
    runtime_dsn,
    tenant_scope="tenant-a",
    tenant_scope_sha256="a" * 64,
)


def create_decoy(attacker, *, evidence_id=None):
    attacker.execute(
        "CREATE SCHEMA public AUTHORIZATION "
        "cwl_llm_batch_outbox_schema_race_owner"
    )
    attacker.execute(
        "GRANT USAGE ON SCHEMA public "
        "TO cwl_llm_batch_outbox_schema_race_runtime"
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
        "evidence_ref_sha256 text NOT NULL, "
        "UNIQUE (tenant_scope, evidence_id)"
        ")"
    )
    attacker.execute(
        "GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox "
        "TO cwl_llm_batch_outbox_schema_race_runtime"
    )
    if evidence_id is not None:
        attacker.execute(
            "INSERT INTO public.llm_context_lifecycle_outbox ("
            "tenant_scope, evidence_id, event_type, tenant_scope_sha256, "
            "subject_ref_sha256, authority_ref_sha256, origin_ref_sha256, "
            "truth_status, valid_time, system_time, provenance_ref_sha256, "
            "evidence_ref_sha256) VALUES ("
            "'tenant-a', %s, 'batch.lifecycle.observed', "
            "%s, %s, %s, %s, 'observed', "
            "'1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', %s, %s"
            ")",
            (evidence_id, "a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64),
        )


class ReadRacingCursor:
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
        if (
            not self.attack_attempted
            and type(row) is tuple
            and len(row) == 3
            and row[:2] == (False, False)
        ):
            self.attack_attempted = True
            try:
                with self._attacker_connection.cursor() as attacker:
                    attacker.execute("SET LOCAL lock_timeout = '500ms'")
                    attacker.execute("ALTER SCHEMA public RENAME TO public_admitted")
                    create_decoy(attacker, evidence_id="admission-schema-race")
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
            cursor = ReadRacingCursor(raw_cursor, attacker_connection)
            read_error = None
            try:
                store.load_in_transaction(
                    cursor,
                    "admission-schema-race",
                    for_update=False,
                )
            except ConfigError as exc:
                read_error = exc
            finally:
                runtime_connection.rollback()

assert cursor.attack_attempted, "hostile schema rename was not exercised"
assert cursor.attack_committed, "schema owner could not exercise namespace rebinding"
assert not cursor.attack_blocked, "schema rename unexpectedly depended on the relation lock"
assert read_error is not None, "runtime accepted a replacement qualified-name binding"
assert "relation identity changed" in str(read_error)

with psycopg.connect(owner_dsn) as reset_connection:
    with reset_connection.cursor() as reset:
        reset.execute("DROP SCHEMA public CASCADE")
        reset.execute("ALTER SCHEMA public_admitted RENAME TO public")
        reset.execute(
            "GRANT USAGE ON SCHEMA public "
            "TO cwl_llm_batch_outbox_schema_race_runtime"
        )
        reset.execute(
            "GRANT SELECT, INSERT ON public.llm_context_lifecycle_outbox "
            "TO cwl_llm_batch_outbox_schema_race_runtime"
        )
    reset_connection.commit()

candidate = ContextLifecycleEvidenceSeed(
    evidence_id="admission-schema-write-race",
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


class WriteRacingCursor:
    def __init__(self, cursor, attacker_connection):
        self._cursor = cursor
        self._attacker_connection = attacker_connection
        self._last_sql = ""
        self.attack_attempted = False
        self.attack_committed = False
        self.attack_blocked = False

    def execute(self, sql, *args, **kwargs):
        self._last_sql = " ".join(sql.split())
        return self._cursor.execute(sql, *args, **kwargs)

    def fetchone(self):
        row = self._cursor.fetchone()
        if (
            not self.attack_attempted
            and self._last_sql.startswith("SELECT live_relation.oid")
            and type(row) is tuple
            and len(row) == 12
            and row[0] is True
            and all(value is None for value in row[1:])
        ):
            self.attack_attempted = True
            try:
                with self._attacker_connection.cursor() as attacker:
                    attacker.execute("SET LOCAL lock_timeout = '500ms'")
                    attacker.execute("ALTER SCHEMA public RENAME TO public_admitted_write")
                    create_decoy(attacker)
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
            cursor = WriteRacingCursor(raw_cursor, attacker_connection)
            write_error = None
            try:
                store.enqueue_in_transaction(cursor, candidate)
            except ConfigError as exc:
                write_error = exc
            finally:
                runtime_connection.rollback()

assert cursor.attack_attempted, "hostile write-side schema rename was not exercised"
assert cursor.attack_committed, "schema owner could not exercise write-side rebinding"
assert not cursor.attack_blocked, "write-side schema rename unexpectedly depended on table lock"
assert write_error is not None, "runtime inserted through a replacement qualified-name binding"
assert "relation identity changed" in str(write_error)

with psycopg.connect(owner_dsn) as verifier_connection:
    with verifier_connection.cursor() as verifier:
        verifier.execute(
            "SELECT count(*) FROM public.llm_context_lifecycle_outbox "
            "WHERE evidence_id = %s",
            (candidate.evidence_id,),
        )
        decoy_count = verifier.fetchone()[0]
        verifier.execute(
            "SELECT count(*) FROM public_admitted_write.llm_context_lifecycle_outbox "
            "WHERE evidence_id = %s",
            (candidate.evidence_id,),
        )
        admitted_count = verifier.fetchone()[0]

assert decoy_count == 0, "identity mismatch still wrote the replacement relation"
assert admitted_count == 0, "identity mismatch unexpectedly wrote the admitted relation"
PY
