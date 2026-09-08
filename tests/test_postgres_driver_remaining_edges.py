"""Remaining authority edges for the commercial PostgreSQL driver migration."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

import pg_llm_batch.pg8000_candidate_driver_port as candidate_port
import pg_llm_batch.pg8000_candidate_service_file as candidate_service_file
import pg_llm_batch.psycopg_driver_adapter as psycopg_adapter
from pg_llm_batch.pg8000_candidate_driver_port import (
    Pg8000CandidateDriverAdapter,
    Pg8000CandidateInvalidConninfoError,
)
from pg_llm_batch.pg8000_driver_candidate_adapter import (
    Pg8000CandidateAdapterError,
    Pg8000CandidateConnectionAdapter,
)
from pg_llm_batch.pg8000_driver_candidate_errors import (
    is_pg8000_candidate_undefined_function,
)
from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
    REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS,
    PostgresDriverCandidateEvidence,
    PostgresDriverCandidateEvidenceError,
)
from pg_llm_batch.psycopg_driver_adapter import (
    PsycopgCursorAdapter,
    PsycopgDriverAdapter,
)


def _candidate_module(*, include_connect: bool = False) -> ModuleType:
    """Build exact DB-API candidate authority without importing the package."""
    module = ModuleType("candidate_pg8000_errors")

    class ProgrammingErrorCandidate(Exception):
        pass

    module.apilevel = "2.0"
    module.paramstyle = "format"
    module.threadsafety = 1
    module.ProgrammingError = ProgrammingErrorCandidate
    if include_connect:
        module.connect = lambda **_kwargs: _TransactionConnection()
    return module


class _TransactionConnection:
    """Inject transaction and cleanup failures without a database."""

    def __init__(
        self,
        *,
        commit_error: BaseException | None = None,
        rollback_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.autocommit = False

    def cursor(self) -> Any:
        raise AssertionError("not used")

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error


def test_candidate_exit_preserves_transaction_error_over_cleanup_error() -> None:
    """A failed commit remains the primary result if physical close also fails."""
    commit_error = RuntimeError("commit failed")
    adapter = Pg8000CandidateConnectionAdapter(
        _TransactionConnection(
            commit_error=commit_error,
            close_error=OSError("close failed"),
        )
    )

    with pytest.raises(RuntimeError, match="commit failed") as caught:
        adapter.__exit__(None, None, None)
    assert caught.value is commit_error


def test_candidate_exit_preserves_application_error_over_cleanup_error() -> None:
    """A successful rollback cannot let a later close failure replace caller failure."""
    application_error = ValueError("application failed")
    adapter = Pg8000CandidateConnectionAdapter(
        _TransactionConnection(close_error=OSError("close failed"))
    )

    with pytest.raises(ValueError, match="application failed") as caught:
        adapter.__exit__(ValueError, application_error, None)
    assert caught.value is application_error


def test_candidate_exit_propagates_close_only_failure() -> None:
    """Physical close failure remains visible when transaction exit otherwise succeeds."""
    adapter = Pg8000CandidateConnectionAdapter(
        _TransactionConnection(close_error=OSError("close failed"))
    )

    with pytest.raises(OSError, match="close failed"):
        adapter.__exit__(None, None, None)


def test_candidate_exit_propagates_transaction_failure_after_successful_close() -> None:
    """A failed commit remains visible when physical cleanup itself succeeds."""
    commit_error = RuntimeError("commit failed")
    adapter = Pg8000CandidateConnectionAdapter(
        _TransactionConnection(commit_error=commit_error)
    )

    with pytest.raises(RuntimeError, match="commit failed") as caught:
        adapter.__exit__(None, None, None)
    assert caught.value is commit_error


def test_candidate_error_classifier_rejects_wrong_exact_exception_type() -> None:
    """A message-compatible exception is never SQLSTATE authority."""
    module = _candidate_module()
    assert (
        is_pg8000_candidate_undefined_function(
            RuntimeError({"C": "42883"}),
            dbapi_module=module,
        )
        is False
    )


def test_candidate_error_classifier_rejects_missing_server_payload() -> None:
    """The exact candidate exception class still needs one PostgreSQL response payload."""
    module = _candidate_module()
    error_type = vars(module)["ProgrammingError"]
    assert isinstance(error_type, type)
    assert is_pg8000_candidate_undefined_function(error_type(), dbapi_module=module) is False


def test_candidate_driver_covers_remaining_fail_closed_selector_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise defensive URI, keyword, construction, and SQLSTATE authority edges."""
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        candidate_port._decode_component("%00")
    with pytest.raises(Pg8000CandidateInvalidConninfoError, match="unsupported"):
        candidate_port._parse_postgresql_uri("mysql://batch@localhost/db")
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        candidate_port._parse_postgresql_uri("postgresql:///db")
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        candidate_port._parse_keyword_fields("host=localhost\nuser=batch")
    assert candidate_port._parse_keyword_fields(
        "host=localhost user=batch dbname=db   "
    ) == {"host": "localhost", "user": "batch", "dbname": "db"}

    monkeypatch.setattr(
        candidate_port,
        "urlsplit",
        lambda _dsn: SimpleNamespace(scheme="mysql"),
    )
    with pytest.raises(Pg8000CandidateInvalidConninfoError, match="unsupported"):
        candidate_port._parse_postgresql_uri("postgresql://batch@localhost/db")

    with pytest.raises(Pg8000CandidateAdapterError, match="connection factory"):
        Pg8000CandidateDriverAdapter(_candidate_module())

    module = _candidate_module(include_connect=True)
    driver = Pg8000CandidateDriverAdapter(module)
    error_type = vars(module)["ProgrammingError"]
    assert isinstance(error_type, type)
    assert driver.is_undefined_function(error_type({"C": "42883"})) is True


def test_service_file_preserves_primary_failure_when_close_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Descriptor cleanup cannot replace an already-established service-file failure."""
    monkeypatch.setattr(candidate_service_file.os, "open", lambda *_args: 7)

    def fail_fstat(_descriptor: int) -> object:
        raise OSError("read failed")

    def fail_close(_descriptor: int) -> None:
        raise OSError("close failed")

    monkeypatch.setattr(candidate_service_file.os, "fstat", fail_fstat)
    monkeypatch.setattr(candidate_service_file.os, "close", fail_close)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        candidate_service_file._read_bounded_utf8(Path("unused-service.conf"))


def test_psycopg_adapter_covers_tuple_rows_and_default_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retained adapter keeps tuple identity and omits absent timeout authority."""
    raw_cursor = SimpleNamespace(fetchone=lambda: ("row",))
    assert PsycopgCursorAdapter(raw_cursor).fetchone() == ("row",)

    captured: dict[str, object] = {}

    def connect(dsn: str, **kwargs: object) -> _TransactionConnection:
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return _TransactionConnection()

    monkeypatch.setattr(psycopg_adapter.psycopg, "connect", connect)
    connection = PsycopgDriverAdapter().connect("host=localhost")
    assert captured == {"dsn": "host=localhost", "kwargs": {}}
    connection.close()


def test_candidate_evidence_rejects_unknown_capability_without_count_overflow() -> None:
    """Replacing one required capability with an unknown name hits set authority checks."""
    capabilities = set(REQUIRED_POSTGRES_DRIVER_CAPABILITIES)
    capabilities.remove(next(iter(capabilities)))
    capabilities.add("unknown_capability")

    with pytest.raises(PostgresDriverCandidateEvidenceError, match="unknown capability"):
        PostgresDriverCandidateEvidence(
            package_name="candidate-driver",
            package_version="1.2.3",
            license_spdx="BSD-3-Clause",
            license_report_sha256="d" * 64,
            python_versions=tuple(sorted(REQUIRED_POSTGRES_DRIVER_PYTHON_VERSIONS)),
            source_commit_sha="a" * 40,
            artifact_sha256="b" * 64,
            vulnerability_report_sha256="c" * 64,
            capability_report_sha256="e" * 64,
            known_vulnerability_ids=(),
            capabilities=frozenset(capabilities),
        )
