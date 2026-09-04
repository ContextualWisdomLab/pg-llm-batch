"""Exercise the exact pg8000 candidate against a real PostgreSQL boundary.

This script is intentionally outside pytest discovery. CI installs one immutable
pg8000 candidate artifact and runs this smoke against the repository PostgreSQL
image without adding the candidate to the production dependency graph. The
checks cover the portable connection/cursor ACL, thread-affine connection use,
transaction, parameter, JSONB, UUID/timestamp, affected-row, and transaction-local
tenant semantics that must be proven before candidate promotion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import metadata
import os
from pathlib import Path
import uuid

from pg8000 import dbapi

from pg_llm_batch.pg8000_driver_candidate_adapter import validate_pg8000_dbapi_module
from pg_llm_batch.pg8000_thread_affine_candidate_adapter import (
    Pg8000ThreadAffineCandidateConnectionAdapter,
)

_EXPECTED_VERSION = "1.31.5"
_EXPECTED_DATABASE = "pgllm"
_EXPECTED_USER = "pgllm"


def _raw_connection() -> object:
    """Open one finite local candidate connection using the CI-owned password file."""
    password_file = os.environ.get("PG8000_CANDIDATE_PASSWORD_FILE")
    if not password_file:
        raise RuntimeError("PG8000_CANDIDATE_PASSWORD_FILE is required")
    try:
        password = Path(password_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise RuntimeError("PG8000 candidate password file could not be read") from None
    if not password:
        raise RuntimeError("PG8000 candidate password file is empty")
    return dbapi.connect(
        user=_EXPECTED_USER,
        password=password,
        host="127.0.0.1",
        port=5432,
        database=_EXPECTED_DATABASE,
        timeout=5,
    )


def _cleanup() -> None:
    """Remove candidate-only database objects even after a prior interrupted smoke."""
    raw = _raw_connection()
    try:
        raw.autocommit = True
        cursor = raw.cursor()
        try:
            cursor.execute("DROP TABLE IF EXISTS pg8000_candidate_contract")
            cursor.execute("DROP ROLE IF EXISTS pg8000_candidate_reader")
        finally:
            cursor.close()
    finally:
        raw.close()


def _prepare_rls_fixture() -> tuple[uuid.UUID, datetime]:
    """Create an ephemeral RLS fixture and return exact typed evidence values."""
    evidence_uuid = uuid.uuid4()
    evidence_time = datetime.now(timezone.utc).replace(microsecond=0)
    raw = _raw_connection()
    try:
        raw.autocommit = True
        connection = Pg8000ThreadAffineCandidateConnectionAdapter(raw)
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
                    {"candidate": "pg8000", "visible": True},
                    "tenant-b",
                    uuid.uuid4(),
                    evidence_time,
                    {"candidate": "pg8000", "visible": False},
                ),
            )
            if cursor.row_count() != 2:
                raise AssertionError("pg8000 candidate row-count evidence is not exact")
    finally:
        raw.close()
    return evidence_uuid, evidence_time


def _assert_transaction_rollback() -> None:
    """Prove the package connection context rolls an exceptional write back."""
    raw = _raw_connection()
    adapter = Pg8000ThreadAffineCandidateConnectionAdapter(raw)
    try:
        with adapter as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE pg8000_candidate_contract
                    SET evidence_json = %s
                    WHERE tenant_scope = %s
                    """,
                    ({"rolled_back": True}, "tenant-a"),
                )
                if cursor.row_count() != 1:
                    raise AssertionError("candidate rollback probe did not update one row")
                raise RuntimeError("candidate rollback probe")
    except RuntimeError as exc:
        if str(exc) != "candidate rollback probe":
            raise


def _assert_typed_rls_read(
    expected_uuid: uuid.UUID,
    expected_time: datetime,
) -> None:
    """Prove transaction-local tenant scope and typed result semantics together."""
    raw = _raw_connection()
    adapter = Pg8000ThreadAffineCandidateConnectionAdapter(raw)
    with adapter as connection:
        with connection.cursor() as cursor:
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
    validate_pg8000_dbapi_module(dbapi)

    raw = _raw_connection()
    adapter = Pg8000ThreadAffineCandidateConnectionAdapter(raw)
    with adapter as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, %s::text", ("bound",))
            if cursor.fetchone() != (_EXPECTED_DATABASE, _EXPECTED_USER, "bound"):
                raise AssertionError("candidate parameter/result semantics changed")

    _cleanup()
    try:
        evidence_uuid, evidence_time = _prepare_rls_fixture()
        _assert_transaction_rollback()
        _assert_typed_rls_read(evidence_uuid, evidence_time)
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
