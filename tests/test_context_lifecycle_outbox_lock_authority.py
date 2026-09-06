# SPDX-License-Identifier: Apache-2.0
"""Tests for lifecycle-outbox replay-serialization authority validation."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.context_lifecycle_outbox import (
    PostgresContextLifecycleOutboxStore,
    _event_identity_lock_key,
)
from pg_llm_batch.exceptions import ValidationError


TENANT_SCOPE_SHA256 = "a" * 64


class RecordingCursor:
    """Fail if invalid lock authority reaches PostgreSQL interaction."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []
        self.result: Any = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record one SQL call so validation ordering remains observable."""
        self.calls.append((sql, params))
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT admitted_role.rolsuper"):
            self.result = (False, False)
        elif normalized.startswith("SELECT pg_catalog.pg_advisory_xact_lock"):
            self.result = (None,)
        else:
            self.result = None

    def fetchone(self) -> Any:
        """Return the current deterministic catalog/query result."""
        return self.result


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

    assert len(cursor.calls) == 3
    assert cursor.calls[0][0].startswith("SELECT admitted_role.rolsuper")
    assert cursor.calls[1][0].startswith("SELECT pg_catalog.set_config")
    assert "pg_advisory_xact_lock" not in cursor.calls[2][0]
    assert "FOR UPDATE" not in cursor.calls[2][0]


def test_load_in_transaction_serializes_identity_without_row_update_lock() -> None:
    """Compare-and-swap reads use a transaction advisory lock, not UPDATE privilege."""
    cursor = RecordingCursor()

    assert _store().load_in_transaction(cursor, "event-1", for_update=True) is None

    assert len(cursor.calls) == 4
    assert cursor.calls[0][0].startswith("SELECT admitted_role.rolsuper")
    assert cursor.calls[1][0].startswith("SELECT pg_catalog.set_config")
    assert cursor.calls[2] == (
        "SELECT pg_catalog.pg_advisory_xact_lock(%s)",
        (_event_identity_lock_key("standalone", "event-1"),),
    )
    assert "FOR UPDATE" not in cursor.calls[3][0]


def test_event_identity_lock_key_is_stable_signed_bigint() -> None:
    """The same tenant/event identity maps to one PostgreSQL bigint lock key."""
    key = _event_identity_lock_key("tenant-a", "event-1")

    assert key == _event_identity_lock_key("tenant-a", "event-1")
    assert key != _event_identity_lock_key("tenant-b", "event-1")
    assert key != _event_identity_lock_key("tenant-a", "event-2")
    assert -(2**63) <= key < 2**63
