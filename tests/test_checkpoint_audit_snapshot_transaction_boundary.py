# SPDX-License-Identifier: Apache-2.0
"""Transaction-boundary contracts for checkpoint-audit snapshot manifests."""

from __future__ import annotations

from pathlib import Path
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
    """Expose transaction characteristics plus libpq-style transaction state."""

    def __init__(
        self,
        *,
        transaction_status: Any,
        isolation: Any = ("repeatable read",),
        read_only: Any = ("on",),
    ) -> None:
        self.connection = _Connection(transaction_status)
        self.isolation = isolation
        self.read_only = read_only
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Capture one normalized SQL statement and parameters."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> Any:
        """Return evidence for the transaction characteristic most recently queried."""
        if self.calls and self.calls[-1][0] == "SHOW transaction_read_only":
            return self.read_only
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


def test_snapshot_manifest_rejects_active_read_write_transaction_before_page_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest cannot include audit rows that may disappear with the caller rollback."""
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
    cursor = _IsolationCursor(
        transaction_status=_TransactionStatus("INTRANS"),
        read_only=("off",),
    )

    with pytest.raises(RuntimeError, match="read-only"):
        store.build_audit_snapshot_manifest_in_transaction(
            cursor,
            "worker-a",
            "batch-1",
            "default",
        )

    assert cursor.calls == [
        ("SHOW transaction_isolation", ()),
        ("SHOW transaction_read_only", ()),
    ]
    assert page_called is False


def test_authoritative_snapshot_docs_reject_autocommit_session_isolation() -> None:
    """Authoritative contracts must state the active-transaction requirement."""
    paths = (
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("ARCHITECTURE.md"),
        Path("CHANGELOG.md"),
        Path("docs/adr/0012-checkpoint-audit-snapshot-manifests.md"),
        Path("docs/checkpoint-audit.md"),
        Path("docs/doctoring/checkpoint-audit-snapshot-manifests.md"),
    )
    for path in paths:
        text = " ".join(path.read_text(encoding="utf-8").split()).lower()
        assert "active postgresql transaction" in text, path
        assert "autocommit" in text, path
        assert "repeatable read" in text, path


def test_snapshot_doctoring_cites_psycopg_transaction_status() -> None:
    """Doctoring records the primary driver evidence used by the fail-closed gate."""
    text = " ".join(
        Path("docs/doctoring/checkpoint-audit-snapshot-manifests.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "ConnectionInfo.transaction_status" in text
    assert "Psycopg 3" in text
    assert "APA 7" in text
