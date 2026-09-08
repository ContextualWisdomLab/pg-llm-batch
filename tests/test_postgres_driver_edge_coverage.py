"""Edge contracts for retained and candidate PostgreSQL driver boundaries."""

from __future__ import annotations

import builtins
from types import ModuleType
from typing import Any

import pytest
from psycopg import ProgrammingError

import pg_llm_batch.postgres_driver_runtime as runtime
import pg_llm_batch.psycopg_driver_adapter as psycopg_adapter
from pg_llm_batch.pg8000_candidate_driver_port import (
    Pg8000CandidateDriverAdapter,
    Pg8000CandidateInvalidConninfoError,
    _copy_parameter_mapping,
    _parse_port,
    _parse_postgresql_uri,
    _read_keyword_value,
    _validate_parameter_mapping,
)
from pg_llm_batch.pg8000_driver_candidate_errors import (
    Pg8000CandidateErrorEvidenceError,
    is_pg8000_candidate_undefined_function,
)
from pg_llm_batch.psycopg_driver_adapter import (
    PsycopgConnectionAdapter,
    PsycopgCursorAdapter,
    PsycopgDriverAdapter,
    PsycopgDriverAdapterError,
    PsycopgInvalidConninfoError,
)


def _candidate_module() -> ModuleType:
    """Build one admitted-shaped pg8000 DB-API module without importing pg8000."""
    module = ModuleType("candidate_pg8000")

    class DatabaseErrorCandidate(Exception):
        pass

    def connect(**_kwargs: object) -> _RawCandidateConnection:
        return _RawCandidateConnection()

    module.apilevel = "2.0"
    module.threadsafety = 1
    module.paramstyle = "format"
    module.DatabaseError = DatabaseErrorCandidate
    module.connect = connect
    return module


class _RawCandidateCursor:
    """Minimal raw cursor for candidate connection construction."""

    rowcount = 0

    def execute(self, _query: str, _params: object | None = None) -> None:
        return None

    def executemany(self, _query: str, _params: object) -> None:
        return None

    def fetchone(self) -> None:
        return None

    def fetchmany(self, _size: int) -> list[object]:
        return []

    def fetchall(self) -> list[object]:
        return []

    def close(self) -> None:
        return None


class _RawCandidateConnection:
    """Minimal raw pg8000-shaped connection for candidate construction."""

    def __init__(self) -> None:
        self.autocommit = False

    def cursor(self) -> _RawCandidateCursor:
        return _RawCandidateCursor()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user%FF@localhost/db",
        "postgresql://user@localhost",
        "postgresql://user@localhost/db/extra",
        "postgresql://user@[::1/db",
    ],
)
def test_candidate_uri_rejects_unrepresentable_or_malformed_authority(dsn: str) -> None:
    """Malformed URI authority fails inside the bounded candidate parser."""
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _parse_postgresql_uri(dsn)


def test_candidate_uri_accepts_postgres_alias_empty_password_and_default_port() -> None:
    """The admitted alias preserves an explicit empty password and default port."""
    assert _parse_postgresql_uri("postgres://user:@localhost/db") == {
        "user": "user",
        "password": "",
        "host": "localhost",
        "port": "5432",
        "dbname": "db",
    }


@pytest.mark.parametrize("value", [True, 0, 65536, "", "abc"])
def test_candidate_port_rejects_non_tcp_values(value: object) -> None:
    """Port normalization accepts neither booleans nor non-TCP values."""
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _parse_port(value)


def test_keyword_reader_covers_empty_and_escape_failure_boundaries() -> None:
    """Keyword parsing handles exact empty input and fails closed on dangling escapes."""
    assert _read_keyword_value("", 0) == ("", 0)
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _read_keyword_value("abc\\", 0)
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _read_keyword_value("abc'", 0)
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _read_keyword_value("'abc'x", 0)


def test_candidate_mapping_rejects_non_mapping_missing_and_empty_identity() -> None:
    """Candidate parameter authority must be a complete built-in textual mapping."""
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _copy_parameter_mapping([])  # type: ignore[arg-type]
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _validate_parameter_mapping({"user": "u", "host": "h"})
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        _validate_parameter_mapping({"user": "", "host": "h", "dbname": "d"})


def test_candidate_adapter_covers_passwordless_connect_ipv6_render_and_classifiers() -> None:
    """Owner-thread candidate use preserves passwordless selectors and IPv6 rendering."""
    module = _candidate_module()
    adapter = Pg8000CandidateDriverAdapter(module)
    connection = adapter.connect("postgresql://user@localhost/db")
    assert connection.is_closed() is False
    rendered = adapter.make_conninfo(
        {"user": "user", "host": "2001:db8::1", "dbname": "db", "port": "5432"}
    )
    assert rendered == "postgresql://user@[2001:db8::1]:5432/db"
    assert adapter.is_invalid_conninfo(Pg8000CandidateInvalidConninfoError("x")) is True
    assert adapter.is_invalid_conninfo(RuntimeError("x")) is False
    adapted = adapter.jsonb({"a": 1})
    assert adapted is not None


def test_candidate_service_selector_requires_nonempty_explicit_resolver() -> None:
    """Service selection never falls back to ambient libpq authority."""
    adapter = Pg8000CandidateDriverAdapter(_candidate_module())
    for dsn in ("service=", "service=prod"):
        with pytest.raises(Pg8000CandidateInvalidConninfoError):
            adapter.parse_conninfo(dsn)


def test_candidate_error_classifier_rejects_shaped_authority_and_payloads() -> None:
    """SQLSTATE classification requires the exact admitted module and payload shape."""
    with pytest.raises(Pg8000CandidateErrorEvidenceError):
        is_pg8000_candidate_undefined_function(RuntimeError(), dbapi_module=object())

    module = _candidate_module()
    error_type = vars(module)["DatabaseError"]
    assert isinstance(error_type, type)
    assert is_pg8000_candidate_undefined_function(error_type("bad"), dbapi_module=module) is False
    assert is_pg8000_candidate_undefined_function(error_type({"C": 42883}), dbapi_module=module) is False
    assert is_pg8000_candidate_undefined_function(error_type({"C": "42883"}), dbapi_module=module) is True


class _RawPsycopgCursor:
    """Drive retained adapter edge cases without a database."""

    def __init__(self) -> None:
        self.rowcount: object = 0
        self.fetchone_value: object | None = None
        self.fetchmany_value: object = []
        self.fetchall_value: object = []

    def fetchone(self) -> object | None:
        return self.fetchone_value

    def fetchmany(self, _size: int) -> object:
        return self.fetchmany_value

    def fetchall(self) -> object:
        return self.fetchall_value


class _LenFailure:
    """Raise while the adapter proves a finite fetch result."""

    def __len__(self) -> int:
        raise TypeError("no finite length")


def test_psycopg_cursor_fail_closed_edges() -> None:
    """Retained adapter normalizes no-row evidence and rejects malformed driver output."""
    raw = _RawPsycopgCursor()
    cursor = PsycopgCursorAdapter(raw)
    assert cursor.fetchone() is None

    raw.fetchone_value = object()
    with pytest.raises(PsycopgDriverAdapterError, match="result row"):
        cursor.fetchone()

    raw.fetchmany_value = _LenFailure()
    with pytest.raises(PsycopgDriverAdapterError, match="fetch result"):
        cursor.fetchmany(1)

    raw.rowcount = -2
    with pytest.raises(PsycopgDriverAdapterError, match="row count"):
        cursor.row_count()


class _ClosedShape:
    """Expose an invalid non-boolean Psycopg closed-state signal."""

    closed = 1


def test_psycopg_connection_rejects_non_boolean_closed_state() -> None:
    """Closed-state authority cannot rely on integer truthiness."""
    with pytest.raises(PsycopgDriverAdapterError, match="closed state"):
        PsycopgConnectionAdapter(_ClosedShape()).is_closed()


def test_psycopg_conninfo_wrappers_narrow_programming_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only conninfo grammar failures become the neutral invalid-selector category."""
    def fail_parse(_dsn: str) -> dict[str, str]:
        raise ProgrammingError("bad")

    def fail_render(**_params: str) -> str:
        raise ProgrammingError("bad")

    monkeypatch.setattr(psycopg_adapter, "conninfo_to_dict", fail_parse)
    monkeypatch.setattr(psycopg_adapter, "make_conninfo", fail_render)
    adapter = PsycopgDriverAdapter()
    with pytest.raises(PsycopgInvalidConninfoError):
        adapter.parse_conninfo("bad")
    with pytest.raises(PsycopgInvalidConninfoError):
        adapter.make_conninfo({"host": "bad"})


def test_runtime_selector_distinguishes_missing_psycopg_from_other_import_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional-client absence is redacted while unrelated package defects propagate."""
    original_import = builtins.__import__

    def missing_psycopg(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith("psycopg_driver_adapter"):
            error = ModuleNotFoundError("missing psycopg")
            error.name = "psycopg"
            raise error
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_psycopg)
    with pytest.raises(runtime.PostgresDriverUnavailableError, match="unavailable"):
        runtime.retained_postgres_driver()

    def missing_other(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith("psycopg_driver_adapter"):
            error = ModuleNotFoundError("missing other")
            error.name = "other_dependency"
            raise error
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_other)
    with pytest.raises(ModuleNotFoundError):
        runtime.retained_postgres_driver()
