# SPDX-License-Identifier: Apache-2.0
"""Database-target authority contracts for readiness probes."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import health


class _ForbiddenPsycopg:
    """Fail if an invalid readiness target reaches libpq connection selection."""

    @staticmethod
    def connect(*_args: Any, **_kwargs: Any) -> None:
        """Prove invalid target values never reach Psycopg/libpq."""
        raise AssertionError("invalid health DSN reached psycopg.connect")


@pytest.mark.parametrize("invalid_dsn", [None, True, 7, b"postgresql://bytes", "", "  \t "])
def test_health_rejects_invalid_database_targets_before_libpq(
    monkeypatch: pytest.MonkeyPatch,
    invalid_dsn: Any,
) -> None:
    """Readiness must not delegate target selection to ambient libpq defaults."""
    monkeypatch.setattr(health, "psycopg", _ForbiddenPsycopg())

    report = health.check_health(invalid_dsn)

    assert report == {
        "ready": False,
        "components": [
            {
                "component": "database",
                "is_ready": False,
                "detail": "invalid Postgres DSN",
            }
        ],
    }
    rendered_value = str(invalid_dsn)
    if rendered_value:
        assert rendered_value not in report["components"][0]["detail"]
