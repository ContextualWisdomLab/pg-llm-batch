"""Exercise the exact pg8000 candidate against a real PostgreSQL boundary.

This script is intentionally outside pytest discovery. CI installs one immutable
pg8000 candidate artifact and runs this smoke against the repository PostgreSQL
image without adding the candidate to the production dependency graph. The
checks cover the candidate URI connection factory, portable connection/cursor
ACL, thread-affine connection use, transaction, parameter, JSONB, UUID/timestamp,
affected-row, narrow PostgreSQL error classification, restore-catalog inspection,
and transaction-local tenant semantics that must be proven before candidate
promotion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import metadata
import os
from pathlib import Path
import uuid

from pg8000 import dbapi

from pg_llm_batch.pg8000_candidate_driver_port import Pg8000CandidateDriverAdapter
from pg_llm_batch.pg8000_driver_candidate_jsonb import adapt_pg8000_jsonb
from pg_llm_batch.postgres_restore_acceptance import inspect_postgres_restore_catalog

_EXPECTED_VERSION = "1.31.5"
_EXPECTED_DATABASE = "pgllm"
_EXPECTED_USER = "pgllm"
_CREDENTIAL_FREE_DSN = "postgresql://pgllm@127.0.0.1:5432/pgllm"


def _candidate_driver() -> Pg8000CandidateDriverAdapter:
    """Bind the exact admitted pg8000 DB-API module to the candidate driver port."""
    return Pg8000CandidateDriverAdapter(dbapi)


def _connection() -> object:
    """Open one finite candidate connection from a private in-memory URI selector."""
    password_file = os.environ.get("PG8000_CANDIDATE_PASSWORD_FILE")
    if not password_file:
        raise RuntimeError("PG8000_CANDIDATE_PASSWORD_FILE is required")
    try:
        password = Path(password_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise RuntimeError("PG8000 candidate password file could not be read") from None
    if not password:
        raise RuntimeError("PG8000 candidate password file is empty")

    driver = _candidate_driver()
    parameters = dict(driver.parse_conninfo(_CREDENTIAL_FREE_DSN))
    parameters["password"] = password
    private_dsn = driver.make_conninfo(parameters)
    return driver.connect(private_dsn, connect_timeout_seconds=5)


def _cleanup() -> None:
    """Remove candidate-only database objects even after a prior interrupted smoke."""
    connection = _connection()
    try:
        connection.set_autocommit(True)
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS pg8000_candidate_contract")
            cursor.execute("DROP ROLE IF EXISTS pg8000_candidate_reader")
    finally:
        connection.close()


def _assert_restore_catalog_inspection() -> None:
    """Prove the candidate can inspect the packaged restore catalog exactly.

    The production restore acceptance query binds finite Python lists through
    ``ANY(%s)`` and consumes catalog booleans and tuple rows. Running that exact
    query through pg8000 closes a driver-parity gap that unit adapters cannot
    prove, without turning the candidate into the production runtime.
    """
    connection = _connection()
    try:
        connection.set_autocommit(True)
        evidence = inspect_postgres_restore_catalog(connection)
        if evidence.required_table_count != 11:
            raise AssertionError("candidate restore catalog table evidence changed")
        if evidence.required_index_count != 2:
            raise AssertionError("candidate restore catalog index evidence changed")
        if evidence.lifecycle_rls_forced is not True:
            raise AssertionError("candidate restore catalog RLS evidence changed")
    finally:
        connection.close()


def _prepare_rls_fixture() -> tuple[uuid.UUID, datetime]:
    """Create an ephemeral RLS fixture and return exact typed evidence values."""
    evidence_uuid = uuid.uuid4()
    evidence_time = datetime.now(timezone.utc).replace(microsecond=0)
    connection = _connection()
    try:
        connection.set_autocommit(True)
        with connection.cursor() as cursor:
            cursor.execute("CREATE ROLE pg8000_candidate_reader NOLOGIN")
            cursor.execute(
                """
                CREATE TABLE pg8000_candidate_contract (
                    tenant_scope TEXT NOT NULL,
                    evidence_uuid UUID NOT NULL,
                    evidence_time TIMESTAMPTZ NOT NULL,
                    evidence_json JSONB NOT NULL
                )
                """
            )
            cursor.execute(
                "ALTER TABLE pg8000_candidate_contract ENABLE ROW LEVEL SECURITY"
            )
            cursor.execute(
                "ALTER TABLE pg8000_candidate_contract FORCE ROW LEVEL SECURITY"
            )
            cursor.execute(
                """
                CREATE POLICY candidate_tenant_scope ON pg8000_candidate_contract
                USING (
                    tenant_scope = current_setting(
                        'pg_llm_batch.tenant_scope', true
                    )
                )
                """
            )
            cursor.execute(
                "GRANT SELECT ON pg8000_candidate_contract TO pg8000_candidate_reader"
            )
            cursor.execute(
                """
                INSERT INTO pg8000_candidate_contract
                    (tenant_scope, evidence_uuid, evidence_time, evidence_json)
                VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)
                """,
                (
                    "tenant-a",
                    evidence_uuid,
                    evidence_time,
                    adapt_pg8000_jsonb({"candidate": "pg8000", "visible": True}),
                    "tenant-b",
                    uuid.uuid4(),
                    evidence_time,
                    adapt_pg8000_jsonb({"candidate": "pg8000", "visible": False}),
                ),
            )
            if cursor.row_count() != 2:
                raise AssertionError("pg8000 candidate row-count evidence is not exact")
    finally:
        connection.close()
    return evidence_uuid, evidence_time


def _assert_transaction_rollback() -> None:
    """Prove the package connection context rolls an exceptional write back."""
    connection = _connection()
    try:
        with connection as transaction:
            with transaction.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE pg8000_candidate_contract
                    SET evidence_json = %s
                    WHERE tenant_scope = %s
                    """,
                    (adapt_pg8000_jsonb({"rolled_back": True}), "tenant-a"),
                )
                if cursor.row_count() != 1:
                    raise AssertionError("candidate rollback probe did not update one row")
                raise RuntimeError("candidate rollback probe")
    except RuntimeError as exc:
        if str(exc) != "candidate rollback probe":
            raise


def _assert_undefined_function_classification() -> None:
    """Prove SQLSTATE-based undefined-function classification on real PostgreSQL."""
    driver = _candidate_driver()
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT pg_llm_batch_candidate_missing_function()")
            except BaseException as error:
                if not driver.is_undefined_function(error):
                    raise AssertionError(
                        "candidate undefined-function classification changed"
                    ) from error
            else:
                raise AssertionError("candidate undefined-function probe unexpectedly exists")
        connection.rollback()
    finally:
        connection.close()


def _assert_typed_rls_read(
    expected_uuid: uuid.UUID,
    expected_time: datetime,
) -> None:
    """Prove transaction-local tenant scope and typed result semantics together."""
    connection = _connection()
    with connection as transaction:
        with transaction.cursor() as cursor:
            cursor.execute("SET ROLE pg8000_candidate_reader")
            cursor.execute(
                "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
                ("tenant-a",),
            )
            cursor.execute(
                """
                SELECT tenant_scope, evidence_uuid, evidence_time, evidence_json
                FROM pg8000_candidate_contract
                ORDER BY tenant_scope
                """
            )
            rows = cursor.fetchmany(1)
            if len(rows) != 1:
                raise AssertionError("RLS candidate read exceeded one visible tenant row")
            tenant_scope, evidence_uuid, evidence_time, evidence_json = rows[0]
            if tenant_scope != "tenant-a":
                raise AssertionError("transaction-local tenant scope was not preserved")
            if evidence_uuid != expected_uuid:
                raise AssertionError("UUID adaptation changed candidate evidence")
            if evidence_time != expected_time:
                raise AssertionError("timestamp adaptation changed candidate evidence")
            if evidence_json != {"candidate": "pg8000", "visible": True}:
                raise AssertionError("JSONB adaptation changed candidate evidence")
            if cursor.fetchmany(1):
                raise AssertionError("RLS exposed another tenant through the candidate")


def main() -> None:
    """Run exact-artifact and real-PostgreSQL candidate acceptance probes."""
    if metadata.version("pg8000") != _EXPECTED_VERSION:
        raise AssertionError("unexpected pg8000 candidate version")
    _candidate_driver()

    connection = _connection()
    with connection as transaction:
        with transaction.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, %s::text", ("bound",))
            if cursor.fetchone() != (_EXPECTED_DATABASE, _EXPECTED_USER, "bound"):
                raise AssertionError("candidate parameter/result semantics changed")

    _assert_restore_catalog_inspection()
    _assert_undefined_function_classification()
    _cleanup()
    try:
        evidence_uuid, evidence_time = _prepare_rls_fixture()
        _assert_transaction_rollback()
        _assert_typed_rls_read(evidence_uuid, evidence_time)
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
