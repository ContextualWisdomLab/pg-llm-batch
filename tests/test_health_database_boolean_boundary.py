# SPDX-License-Identifier: Apache-2.0
"""Fail-closed database readiness type contracts."""

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
