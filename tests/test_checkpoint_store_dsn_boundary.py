# SPDX-License-Identifier: Apache-2.0
"""Database-target regressions for the durable checkpoint store."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.checkpoint_store as checkpoint_store
from pg_llm_batch.checkpoint_store import (
    PostgresBatchResultCheckpointStore,
    apply_result_checkpoint_schema,
)
from pg_llm_batch.exceptions import ConfigError


@pytest.mark.parametrize("postgres_dsn", (None, "", " \t\n"))
def test_checkpoint_surfaces_reject_missing_database_targets(
    monkeypatch: pytest.MonkeyPatch,
    postgres_dsn: Any,
) -> None:
    """Store and migration entrypoints must fail before libpq environment fallback."""
    connection_attempts: list[Any] = []
    monkeypatch.setattr(checkpoint_store, "_require_psycopg", lambda: None)
    monkeypatch.setattr(
        checkpoint_store,
        "psycopg",
        type(
            "Driver",
            (),
            {"connect": lambda _self, value: connection_attempts.append(value)},
        )(),
    )

    with pytest.raises(ConfigError, match="Postgres DSN"):
        PostgresBatchResultCheckpointStore(postgres_dsn)
    with pytest.raises(ConfigError, match="Postgres DSN"):
        apply_result_checkpoint_schema(postgres_dsn)

    assert connection_attempts == []
