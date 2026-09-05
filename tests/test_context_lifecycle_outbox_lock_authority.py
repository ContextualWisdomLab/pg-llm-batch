# SPDX-License-Identifier: Apache-2.0
"""Tests for lifecycle-outbox row-lock authority validation."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore
from pg_llm_batch.exceptions import ValidationError


TENANT_SCOPE_SHA256 = "a" * 64


class RecordingCursor:
    """Fail if invalid lock authority reaches PostgreSQL interaction."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record one SQL call so validation ordering remains observable."""
        self.calls.append((sql, params))

    def fetchone(self) -> None:
        """Return no row for the valid unlocked control case."""
        return None


class BehaviorBearingLockAuthority:
    """Expose behavior that must never execute during lock-mode validation."""

    def __bool__(self) -> bool:
        """Fail if product code relies on caller-controlled truthiness."""
        raise AssertionError("behavior-bearing lock authority executed")


def _store() -> PostgresContextLifecycleOutboxStore:
    """Create one explicitly bound store without opening a database connection."""
    return PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope_sha256=TENANT_SCOPE_SHA256,
    )


@pytest.mark.parametrize(
    "for_update",
    (1, "true", None, BehaviorBearingLockAuthority()),
)
def test_load_in_transaction_requires_exact_boolean_lock_authority(
    for_update: Any,
) -> None:
    """Invalid lock authority must fail before truthiness or database interaction."""
    cursor = RecordingCursor()

    with pytest.raises(ValidationError) as raised:
        _store().load_in_transaction(
            cursor,
            "event-1",
            for_update=for_update,  # type: ignore[arg-type]
        )

    assert raised.value.details == {
        "field": "for_update",
        "value": "<redacted>",
        "reason": "must be an exact boolean",
    }
    assert cursor.calls == []


def test_load_in_transaction_accepts_exact_false_lock_authority() -> None:
    """The ordinary unlocked read retains its transaction-local tenant binding."""
    cursor = RecordingCursor()

    assert _store().load_in_transaction(cursor, "event-1", for_update=False) is None

    assert len(cursor.calls) == 2
    assert cursor.calls[0][0].startswith("SELECT pg_catalog.set_config")
    assert "FOR UPDATE" not in cursor.calls[1][0]
