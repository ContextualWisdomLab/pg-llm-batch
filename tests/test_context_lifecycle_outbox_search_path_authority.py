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


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = REPOSITORY_ROOT / "AGENTS.md"
TENANT_SCOPE_SHA256 = "a" * 64


class RecordingCursor:
    """Record SQL order while emulating admitted role authority and an empty outbox."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.result: Any = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record one statement and emulate only the bounded read path."""
        normalized = " ".join(sql.split())
        parameters = params or ()
        self.calls.append((normalized, parameters))
        if normalized.startswith("SELECT admitted_role.rolsuper"):
            self.result = (False, False)
        elif normalized.startswith("SELECT pg_catalog.set_config"):
            self.result = (parameters[0],)
        elif normalized.startswith("SELECT evidence_id"):
            self.result = None
        else:
            self.result = None

    def fetchone(self) -> Any:
        """Return the result from the preceding statement."""
        return self.result


def test_runtime_qualifies_authority_without_mutating_caller_search_path() -> None:
    """Outbox SQL must resist ambient lookup without changing caller transaction state."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256=TENANT_SCOPE_SHA256,
    )
    cursor = RecordingCursor()

    assert store.load_in_transaction(cursor, "event-1") is None

    statements = [sql for sql, _ in cursor.calls]
    assert all(not sql.startswith("SET LOCAL search_path") for sql in statements)
    assert statements[0].startswith("SELECT admitted_role.rolsuper")
    assert statements[1].startswith("SELECT pg_catalog.set_config")
    # ONLY is intentional: inherited relations are outside the canonical owner table.
    assert "FROM ONLY public.llm_context_lifecycle_outbox" in statements[2]


def test_forward_and_rollback_migrations_pin_search_path_inside_do_block() -> None:
    """Installer-controlled search_path must be replaced before object lookup or DDL."""
    binding = (
        "PERFORM pg_catalog.set_config("
        "'search_path', 'pg_catalog, public, pg_temp', true);"
    )
    migration = Path(MIGRATION_PATH).read_text(encoding="utf-8")
    rollback = Path(ROLLBACK_PATH).read_text(encoding="utf-8")

    assert binding in migration
    create_table = "CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox"
    assert create_table in migration
    assert migration.index(binding) < migration.index(create_table)
    assert binding in rollback
    assert rollback.index(binding) < rollback.index("to_regclass")


def test_agent_contract_names_callable_security_definer_search_path_boundary() -> None:
    """Owner instructions must preserve the runtime definer name-resolution guard."""
    agents = " ".join(AGENTS_PATH.read_text(encoding="utf-8").split())

    assert "SECURITY DEFINER" in agents
    assert "search_path = pg_catalog, pg_temp" in agents
    assert "before tenant binding or outbox data SQL" in agents
