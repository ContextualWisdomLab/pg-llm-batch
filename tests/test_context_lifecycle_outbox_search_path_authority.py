# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox PostgreSQL name-resolution authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pg_llm_batch.context_lifecycle_outbox import (
    MIGRATION_PATH,
    ROLLBACK_PATH,
    PostgresContextLifecycleOutboxStore,
)


TENANT_SCOPE_SHA256 = "a" * 64
_CANONICAL_SEARCH_PATH = "pg_catalog, public, pg_temp"


class RecordingCursor:
    """Record SQL order while returning an empty durable outbox result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.result: Any = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record one statement and emulate only the bounded read path."""
        normalized = " ".join(sql.split())
        parameters = params or ()
        self.calls.append((normalized, parameters))
        if normalized.startswith("SELECT set_config"):
            self.result = (parameters[0],)
        elif normalized.startswith("SELECT evidence_id"):
            self.result = None
        else:
            self.result = None

    def fetchone(self) -> Any:
        """Return the result from the preceding statement."""
        return self.result


def test_runtime_pins_search_path_before_tenant_and_table_resolution() -> None:
    """Caller session search_path must not redirect tenant binding or outbox SQL."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256=TENANT_SCOPE_SHA256,
    )
    cursor = RecordingCursor()

    assert store.load_in_transaction(cursor, "event-1") is None

    statements = [sql for sql, _ in cursor.calls]
    assert statements[0] == f"SET LOCAL search_path = {_CANONICAL_SEARCH_PATH}"
    assert statements[1].startswith("SELECT set_config")
    assert statements[2].startswith("SELECT evidence_id")


def test_forward_and_rollback_migrations_pin_search_path_inside_do_block() -> None:
    """Installer-controlled search_path must be replaced before object lookup or DDL."""
    binding = (
        "PERFORM pg_catalog.set_config("
        "'search_path', 'pg_catalog, public, pg_temp', true);"
    )
    migration = Path(MIGRATION_PATH).read_text(encoding="utf-8")
    rollback = Path(ROLLBACK_PATH).read_text(encoding="utf-8")

    assert binding in migration
    assert migration.index(binding) < migration.index(
        "CREATE TABLE IF NOT EXISTS llm_context_lifecycle_outbox"
    )
    assert binding in rollback
    assert rollback.index(binding) < rollback.index("to_regclass")
