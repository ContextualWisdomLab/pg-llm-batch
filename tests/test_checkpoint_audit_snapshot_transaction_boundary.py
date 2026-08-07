# SPDX-License-Identifier: Apache-2.0
"""Transaction-boundary contracts for checkpoint-audit snapshot manifests."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.checkpoint_audit as checkpoint_audit
from pg_llm_batch.checkpoint_audit import CheckpointAuditPage


class _TransactionStatus:
    """Minimal libpq-style transaction-status double."""

    def __init__(self, name: str) -> None:
        self.name = name


class _ConnectionInfo:
    """Expose one deterministic transaction status through ``connection.info``."""

    def __init__(self, transaction_status: Any) -> None:
        self.transaction_status = transaction_status


class _Connection:
    """Minimal cursor connection double for transaction-state validation."""

    def __init__(self, transaction_status: Any) -> None:
        self.info = _ConnectionInfo(transaction_status)


class _IsolationCursor:
    """Expose isolation evidence plus libpq-style transaction state."""

    def __init__(
        self,
        *,
        transaction_status: Any,
        isolation: Any = ("repeatable read",),
    ) -> None:
        self.connection = _Connection(transaction_status)
        self.isolation = isolation
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Capture one normalized SQL statement and parameters."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> Any:
        """Return the configured transaction-isolation evidence."""
        return self.isolation


@pytest.mark.parametrize(
    "transaction_status",
    (
        _TransactionStatus("IDLE"),
        _TransactionStatus("ACTIVE"),
        _TransactionStatus("INERROR"),
        _TransactionStatus("UNKNOWN"),
        None,
        object(),
    ),
)
def test_snapshot_manifest_requires_one_active_transaction_before_isolation_probe(
    monkeypatch: pytest.MonkeyPatch,
    transaction_status: Any,
) -> None:
    """Session isolation alone cannot turn autocommit pages into one stable snapshot."""
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    page_called = False

    def page(*_args: Any, **_kwargs: Any) -> CheckpointAuditPage:
        nonlocal page_called
        page_called = True
        return CheckpointAuditPage(events=(), next_before_audit_event_id=None)

    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        page,
    )
    cursor = _IsolationCursor(transaction_status=transaction_status)

    with pytest.raises(RuntimeError, match="active PostgreSQL transaction"):
        store.build_audit_snapshot_manifest_in_transaction(
            cursor,
            "worker-a",
            "batch-1",
            "default",
        )

    assert cursor.calls == []
    assert page_called is False


def test_snapshot_manifest_accepts_libpq_intrans_before_checking_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-active transaction may proceed to the existing isolation-level gate."""
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        lambda *_args, **_kwargs: CheckpointAuditPage(
            events=(), next_before_audit_event_id=None
        ),
    )
    cursor = _IsolationCursor(transaction_status=_TransactionStatus("INTRANS"))

    manifest = store.build_audit_snapshot_manifest_in_transaction(
        cursor,
        "worker-a",
        "batch-1",
        "default",
    )

    assert manifest.event_count == 0
    assert cursor.calls == [("SHOW transaction_isolation", ())]
