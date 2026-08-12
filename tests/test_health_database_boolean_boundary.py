# SPDX-License-Identifier: Apache-2.0
"""Fail-closed database and public readiness contracts."""

from __future__ import annotations

from pg_llm_batch import health


class _Cursor:
    """Return fixed PostgreSQL health rows through a minimal cursor double."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def execute(self, _sql, _params=None):
        return None

    def fetchall(self):
        return list(self._rows)


class _Connection:
    """Expose the fixed cursor through a minimal connection double."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def cursor(self):
        return _Cursor(self._rows)


class _Psycopg:
    """Return one deterministic fake PostgreSQL connection."""

    def __init__(self, rows):
        self._rows = rows

    def connect(self, _dsn, *, connect_timeout):
        assert connect_timeout == 5
        return _Connection(self._rows)


def test_database_readiness_boolean_is_not_truth_coerced(monkeypatch):
    """Malformed database readiness cannot become a true local or HTTP signal."""
    rows = [
        ("database", "false", "malformed database boolean"),
        ("pg_tiktoken", True, "installed"),
        ("com_config", True, "ready"),
    ]
    monkeypatch.setattr(health, "psycopg", _Psycopg(rows))

    report = health.check_health("postgresql://example")

    assert report["ready"] is False
    database = next(
        component
        for component in report["components"]
        if component["component"] == "database"
    )
    assert database["is_ready"] is False
    assert database["detail"] == "malformed database boolean"
    assert health.public_health_report(report)["ready"] is False


def test_local_health_rejects_duplicate_required_components(monkeypatch):
    """Duplicate required database rows cannot make local readiness healthy."""
    rows = [
        ("database", True, "connected"),
        ("database", True, "duplicate observation"),
        ("pg_tiktoken", True, "installed"),
        ("com_config", True, "ready"),
    ]
    monkeypatch.setattr(health, "psycopg", _Psycopg(rows))

    report = health.check_health("postgresql://example")

    assert report["ready"] is False
    assert [
        component["detail"]
        for component in report["components"]
        if component["component"] == "database"
    ] == ["connected", "duplicate observation"]


def test_public_health_report_redacts_details_and_unknown_components():
    """HTTP readiness exposes only fixed component names and boolean states."""
    report = {
        "ready": True,
        "components": [
            {
                "component": "database",
                "is_ready": True,
                "detail": "password=secret host=db.internal.example",
            },
            {"component": "pg_tiktoken", "is_ready": True, "detail": "installed"},
            {"component": "com_config", "is_ready": True, "detail": "ready"},
            {
                "component": "internal_cluster_primary_host",
                "is_ready": False,
                "detail": "db-07.internal.example",
            },
        ],
    }

    assert health.public_health_report(report) == {
        "ready": True,
        "components": [
            {"component": "database", "is_ready": True},
            {"component": "pg_tiktoken", "is_ready": True},
            {"component": "com_config", "is_ready": True},
        ],
    }


def test_public_health_report_rejects_duplicate_required_components():
    """Duplicate required observations cannot yield a healthy public decision."""
    report = {
        "ready": True,
        "components": [
            {"component": "database", "is_ready": True},
            {"component": "database", "is_ready": True},
            {"component": "pg_tiktoken", "is_ready": True},
            {"component": "com_config", "is_ready": True},
        ],
    }

    assert health.public_health_report(report) == {
        "ready": False,
        "components": [],
    }
