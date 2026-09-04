"""Candidate driver-port regressions for the permissive PostgreSQL migration.

These tests pin the bounded URI and keyword-conninfo selector slices that pg8000
can exercise without libpq. Service-file I/O and libpq-only options remain
explicit fail-closed gaps; passing this suite must not be interpreted as full
issue #322 admission or production dependency approval.
"""

from __future__ import annotations

from types import ModuleType

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import (
    Pg8000CandidateDriverAdapter,
    Pg8000CandidateInvalidConninfoError,
)
from pg_llm_batch.pg8000_thread_affine_candidate_adapter import (
    Pg8000ThreadAffineCandidateConnectionAdapter,
)


class _ProgrammingError(Exception):
    """Stand in for the exact candidate DB-API ProgrammingError authority."""


def _candidate_module() -> tuple[ModuleType, dict[str, object]]:
    """Build one DB-API-shaped module and capture exact connection arguments."""
    module = ModuleType("candidate_dbapi")
    module.apilevel = "2.0"
    module.paramstyle = "format"
    module.threadsafety = 1
    module.ProgrammingError = _ProgrammingError
    captured: dict[str, object] = {}

    def connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    module.connect = connect
    return module, captured


def test_candidate_uri_conninfo_round_trip_preserves_encoded_identity() -> None:
    """Preserve URI identity while decoding values only at the driver boundary."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    params = driver.parse_conninfo(
        "postgresql://batch%20user:p%40ss@db.example:6543/batch%2Fqueue"
    )

    assert params == {
        "user": "batch user",
        "password": "p@ss",
        "host": "db.example",
        "port": "6543",
        "dbname": "batch/queue",
    }
    assert driver.parse_conninfo(driver.make_conninfo(params)) == params


def test_candidate_keyword_conninfo_round_trip_preserves_quoted_identity() -> None:
    """Accept the bounded libpq keyword form needed by existing CLI deployments."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    params = driver.parse_conninfo(
        "host=db.example port=6543 dbname='batch queue' "
        "user='batch user' password='p@ss word'"
    )

    assert params == {
        "host": "db.example",
        "port": "6543",
        "dbname": "batch queue",
        "user": "batch user",
        "password": "p@ss word",
    }
    assert driver.parse_conninfo(driver.make_conninfo(params)) == params


def test_candidate_keyword_conninfo_supports_bare_escaped_and_empty_values() -> None:
    """Preserve bounded libpq escaping without delegating parsing back to libpq."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    params = driver.parse_conninfo(
        r"  host = db.example user=batch dbname=batch\ queue password=   "
    )

    assert params == {
        "host": "db.example",
        "user": "batch",
        "dbname": "batch queue",
        "password": "",
        "port": "5432",
    }
    assert driver.parse_conninfo(driver.make_conninfo(params)) == params


def test_candidate_service_selector_uses_injected_resolver_and_direct_overrides() -> None:
    """Resolve service authority outside the driver and preserve direct overrides."""
    module, _ = _candidate_module()
    resolved_names: list[str] = []

    def resolve_service(service_name: str) -> dict[str, str]:
        resolved_names.append(service_name)
        return {
            "host": "service.example",
            "port": "5432",
            "dbname": "service_db",
            "user": "service_user",
            "password": "service-secret",
        }

    driver = Pg8000CandidateDriverAdapter(module, service_resolver=resolve_service)

    params = driver.parse_conninfo(
        "service=analytics port=6543 dbname='override db'"
    )

    assert resolved_names == ["analytics"]
    assert params == {
        "host": "service.example",
        "port": "6543",
        "dbname": "override db",
        "user": "service_user",
        "password": "service-secret",
    }


def test_candidate_service_connect_uses_resolved_parameters_not_raw_selector() -> None:
    """Keep service-file transport outside pg8000 while connecting with resolved values."""
    module, captured = _candidate_module()

    def resolve_service(service_name: str) -> dict[str, str]:
        assert service_name == "analytics"
        return {
            "host": "127.0.0.1",
            "port": "5544",
            "dbname": "queue",
            "user": "batch",
        }

    driver = Pg8000CandidateDriverAdapter(module, service_resolver=resolve_service)
    connection = driver.connect("service=analytics", connect_timeout_seconds=5)

    assert isinstance(connection, Pg8000ThreadAffineCandidateConnectionAdapter)
    assert captured == {
        "user": "batch",
        "host": "127.0.0.1",
        "port": 5544,
        "database": "queue",
        "timeout": 5,
    }
    assert "service" not in captured
    assert "dsn" not in captured


def test_candidate_conninfo_rejects_unproved_service_and_libpq_options() -> None:
    """Keep selectors outside the proved portable subset fail closed instead of guessing."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    for dsn in (
        "service=production",
        "host=db.example dbname=batch user=batch sslmode=require",
        "postgresql://batch@db.example/batch?sslmode=require",
        "postgresql://batch@db.example/batch#fragment",
    ):
        with pytest.raises(
            Pg8000CandidateInvalidConninfoError,
            match="PostgreSQL connection selector is unsupported",
        ):
            driver.parse_conninfo(dsn)


def test_candidate_service_resolution_rejects_empty_or_unproved_parameters() -> None:
    """Do not let a service resolver expand the candidate beyond admitted fields."""
    module, _ = _candidate_module()

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateDriverAdapter(
            module,
            service_resolver=lambda _: {
                "host": "db.example",
                "dbname": "batch",
                "user": "batch",
            },
        ).parse_conninfo("service=''")

    driver = Pg8000CandidateDriverAdapter(
        module,
        service_resolver=lambda _: {
            "host": "db.example",
            "dbname": "batch",
            "user": "batch",
            "sslmode": "verify-full",
        },
    )
    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is unsupported",
    ):
        driver.parse_conninfo("service=production")


def test_candidate_keyword_conninfo_rejects_ambiguous_or_malformed_grammar() -> None:
    """Reject duplicated authority, malformed quoting, and unproved separators."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    for dsn in (
        "host=db.example user=batch dbname=queue host=other.example",
        "host=db.example user=batch dbname=queue password='unterminated",
        "host=db.example user=batch dbname=queue password=trailing\\",
        "host=db.example user=batch dbname=que'ue",
        "host=db.example user=batch dbname='queue'x",
        "host db.example user=batch dbname=queue",
        "=db.example user=batch dbname=queue",
        "host=db.example\u00a0user=batch dbname=queue",
    ):
        with pytest.raises(Pg8000CandidateInvalidConninfoError):
            driver.parse_conninfo(dsn)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        driver.parse_conninfo(123)  # type: ignore[arg-type]
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        driver.parse_conninfo("")


def test_candidate_conninfo_rejects_ambiguous_or_unproved_host_forms() -> None:
    """Reject multi-host, socket, zone-id, whitespace, and delimiter host forms."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    for dsn in (
        "postgresql://batch@db-a.example,db-b.example/batch",
        "postgresql://batch@db%20name.example/batch",
        "postgresql://batch@%2Fvar%2Frun%2Fpostgresql/batch",
        "postgresql://batch@[fe80::1%25eth0]/batch",
        "postgresql://batch@db\\name.example/batch",
    ):
        with pytest.raises(Pg8000CandidateInvalidConninfoError):
            driver.parse_conninfo(dsn)


def test_candidate_conninfo_rejects_malformed_percent_port_and_control_data() -> None:
    """Reject malformed selectors through one non-content-bearing error contract."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    for dsn in (
        "postgresql://batch%ZZ@db.example/batch",
        "postgresql://batch@db.example:70000/batch",
        "postgresql://batch@db.example/batch\nservice=other",
    ):
        with pytest.raises(Pg8000CandidateInvalidConninfoError):
            driver.parse_conninfo(dsn)


def test_candidate_make_conninfo_rejects_unknown_or_non_string_parameters() -> None:
    """Prevent driver-specific or truthy values from entering the URI renderer."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)
    baseline: dict[str, object] = {
        "user": "batch",
        "host": "db.example",
        "port": "5432",
        "dbname": "batch",
    }

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        driver.make_conninfo({**baseline, "service": "production"})  # type: ignore[arg-type]
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        driver.make_conninfo({**baseline, "port": 5432})  # type: ignore[arg-type]


def test_candidate_connect_maps_uri_and_finite_timeout_without_raw_dsn_forwarding() -> None:
    """Translate the proved URI subset to pg8000 kwargs and retain thread affinity."""
    module, captured = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    connection = driver.connect(
        "postgresql://batch:secret@127.0.0.1:5544/queue",
        connect_timeout_seconds=5,
    )

    assert isinstance(connection, Pg8000ThreadAffineCandidateConnectionAdapter)
    assert captured == {
        "user": "batch",
        "password": "secret",
        "host": "127.0.0.1",
        "port": 5544,
        "database": "queue",
        "timeout": 5,
    }
    assert "dsn" not in captured


def test_candidate_connect_maps_keyword_conninfo_without_raw_dsn_forwarding() -> None:
    """Translate keyword conninfo through the same explicit pg8000 argument boundary."""
    module, captured = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    connection = driver.connect("host=127.0.0.1 user=batch dbname=queue")

    assert isinstance(connection, Pg8000ThreadAffineCandidateConnectionAdapter)
    assert captured == {
        "user": "batch",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "queue",
    }
    assert "dsn" not in captured


@pytest.mark.parametrize("timeout", [True, False, 0, -1, 1.5, "5"])
def test_candidate_connect_rejects_non_positive_or_non_integer_timeout(timeout: object) -> None:
    """Do not coerce booleans, floats, text, or non-positive values into policy."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL driver timeout is invalid",
    ):
        driver.connect(
            "postgresql://batch@127.0.0.1/queue",
            connect_timeout_seconds=timeout,  # type: ignore[arg-type]
        )


def test_candidate_invalid_conninfo_classifier_is_narrow() -> None:
    """Classify only errors created by the candidate selector boundary."""
    module, _ = _candidate_module()
    driver = Pg8000CandidateDriverAdapter(module)

    error = Pg8000CandidateInvalidConninfoError(
        "PostgreSQL connection selector is invalid"
    )
    assert driver.is_invalid_conninfo(error) is True
    assert driver.is_invalid_conninfo(RuntimeError("database unavailable")) is False
