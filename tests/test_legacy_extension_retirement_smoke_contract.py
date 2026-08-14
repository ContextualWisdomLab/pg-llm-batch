# SPDX-License-Identifier: Apache-2.0
"""Static contract for live legacy-extension retirement acceptance."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests" / "smoke_legacy_sql_cleanup.sh"


def test_live_cleanup_smoke_executes_and_repeats_extension_retirement_migration() -> None:
    """The container smoke must exercise successful and idempotent retirement."""
    smoke = SMOKE.read_text(encoding="utf-8")

    migration = "docker/postgres/migrations/retire_legacy_provider_extensions.sql"
    assert migration in smoke
    assert smoke.count(migration) >= 2
    assert "SELECT count(*) FROM pg_extension WHERE extname IN ('pg_cron', 'http')" in smoke


def test_live_cleanup_smoke_preserves_application_evidence_after_retirement() -> None:
    """Extension retirement must prove that application evidence survives."""
    smoke = SMOKE.read_text(encoding="utf-8")

    assert "gateway_retrieval_logs" in smoke
    assert "retirement unexpectedly removed gateway_retrieval_logs" in smoke
    assert "unrelated cron job" in smoke
    assert "retirement unexpectedly accepted an unrelated cron job" in smoke
