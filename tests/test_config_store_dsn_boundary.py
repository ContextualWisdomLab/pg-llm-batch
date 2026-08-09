# SPDX-License-Identifier: Apache-2.0
"""Database-target regressions for configuration and secret stores."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import config as config_module
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from pg_llm_batch.exceptions import ConfigError


@pytest.mark.parametrize("dsn", (None, "", " \t\n", 7))
@pytest.mark.parametrize("store_type", (PostgresConfigStore, SecretStore))
def test_store_rejects_missing_or_non_string_database_target(
    monkeypatch: pytest.MonkeyPatch,
    dsn: Any,
    store_type: type[PostgresConfigStore] | type[SecretStore],
) -> None:
    """Invalid targets must fail before Psycopg or libpq can select a database."""
    connection_attempts: list[Any] = []
    monkeypatch.setattr(
        config_module,
        "psycopg",
        type(
            "Driver",
            (),
            {"connect": lambda _self, value: connection_attempts.append(value)},
        )(),
    )

    with pytest.raises(ConfigError, match="Postgres DSN"):
        store_type(dsn)  # type: ignore[arg-type]

    assert connection_attempts == []


def test_store_preserves_valid_nonblank_dsn_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authority validation must not rewrite valid libpq connection syntax."""
    supplied = " host=database.internal dbname=batch "
    observed: list[str] = []

    class _Connection:
        autocommit = False

        def cursor(self) -> Any:
            raise RuntimeError("stop after target observation")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        config_module,
        "psycopg",
        type(
            "Driver",
            (),
            {"connect": lambda _self, value: observed.append(value) or _Connection()},
        )(),
    )

    with pytest.raises(RuntimeError, match="stop after target observation"):
        PostgresConfigStore(supplied)

    assert observed == [supplied]
