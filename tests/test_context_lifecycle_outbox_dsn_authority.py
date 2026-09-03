# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox PostgreSQL target authority."""

from __future__ import annotations

import pytest

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ConfigError


class BehaviorBearingDsn(str):
    """Expose whether validation executes caller-defined string behavior."""

    def __new__(cls, value: str) -> "BehaviorBearingDsn":
        """Create one hostile string subclass with observable validation behavior."""
        instance = super().__new__(cls, value)
        instance.strip_calls = 0
        return instance

    def strip(self, chars: str | None = None) -> str:
        """Fail if the package executes caller-owned normalization behavior."""
        self.strip_calls += 1
        raise AssertionError("caller-owned DSN behavior executed")


def test_outbox_rejects_behavior_bearing_dsn_before_caller_code() -> None:
    """A DSN subclass must not retain or execute authority at the DB boundary."""
    hostile_dsn = BehaviorBearingDsn("postgresql://unit")

    with pytest.raises(ConfigError, match="Postgres DSN"):
        PostgresContextLifecycleOutboxStore(hostile_dsn)

    assert hostile_dsn.strip_calls == 0
