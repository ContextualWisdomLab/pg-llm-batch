# SPDX-License-Identifier: Apache-2.0
"""Rollback safety contract for durable lifecycle publication evidence."""

from __future__ import annotations

from pathlib import Path

from pg_llm_batch.context_lifecycle_outbox import ROLLBACK_PATH


def test_outbox_rollback_refuses_to_drop_unreconciled_evidence() -> None:
    """Rollback must inspect all tenants and reject a non-empty durable outbox."""
    rollback = Path(ROLLBACK_PATH).read_text(encoding="utf-8")
    assert "to_regclass('llm_context_lifecycle_outbox') IS NOT NULL" in rollback
    assert "NO FORCE ROW LEVEL SECURITY" in rollback
    assert "SELECT 1 FROM llm_context_lifecycle_outbox LIMIT 1" in rollback
    assert "Refusing to drop non-empty llm_context_lifecycle_outbox" in rollback
    assert "DROP TABLE IF EXISTS llm_context_lifecycle_outbox" in rollback
