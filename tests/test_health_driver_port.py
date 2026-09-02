# SPDX-License-Identifier: Apache-2.0
"""Regression tests for readiness checks through the PostgreSQL driver port."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import health


class _HealthCursor:
    """Expose deterministic readiness rows through the driver-neutral cursor shape."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, object | None]] = []

    def execute(self, query: str, params: object | None = None) -> "_HealthCursor":
        """Record the package-authored health query without modifying it."""
        self.executions.append((query, params))
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        """Return all required healthy component rows as canonical tuples."""
        return [
            ("database", True, "connected"),
            ("pg_tiktoken", True, "installed"),
            ("com_config", True, "ready"),
        ]

    def __enter__(self) -> "_HealthCursor":
        """Retain the cursor identity during the readiness transaction."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Release no external resources in the deterministic fake."""
        return None


class _HealthConnection:
    """Retain one cursor for the driver-neutral readiness connection."""

    def __init__(self) -> None:
        self.cursor_value = _HealthCursor()

    def cursor(self) -> _HealthCursor:
        """Return the cursor bound to this exact connection."""
        return self.cursor_value

    def __enter__(self) -> "_HealthConnection":
        """Retain connection identity across context-manager entry."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Release no external resources in the deterministic fake."""
        return None


class _HealthDriver:
    """Capture readiness connection parameters without a concrete client import."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []
        self.connection = _HealthConnection()

    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> _HealthConnection:
        """Preserve the exact DSN and bounded five-second readiness timeout."""
        self.calls.append((dsn, connect_timeout_seconds))
        return self.connection


def test_check_health_uses_injected_driver_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Readiness must work through the replacement seam when Psycopg is unavailable."""
    monkeypatch.setattr(health, "psycopg", None)
    driver = _HealthDriver()

    report = health.check_health(
        "postgresql://example",
        postgres_driver=driver,  # type: ignore[arg-type]
    )

    assert report["ready"] is True
    assert driver.calls == [("postgresql://example", 5)]
    assert driver.connection.cursor_value.executions == [
        ("SELECT component, is_ready, detail FROM pg_llm_batch_health_check()", None)
    ]


def test_check_health_bounds_injected_driver_failures_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacement-driver failures remain bounded without reflecting connection data."""
    monkeypatch.setattr(health, "psycopg", None)
    secret_sentinel = "postgresql://user:private-password@db.example/batch"

    class _BrokenDriver:
        def connect(self, _dsn: str, **_kwargs: Any) -> None:
            raise OSError(f"connection refused for {secret_sentinel}")

    report = health.check_health(
        "postgresql://example",
        postgres_driver=_BrokenDriver(),  # type: ignore[arg-type]
    )

    assert report == {
        "ready": False,
        "components": [
            {
                "component": "database",
                "is_ready": False,
                "detail": "database readiness check failed",
            }
        ],
    }
    assert secret_sentinel not in repr(report)
