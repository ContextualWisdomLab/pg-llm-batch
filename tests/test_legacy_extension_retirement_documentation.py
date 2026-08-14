# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for legacy PostgreSQL extension retirement."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
CHANGELOG = ROOT / "CHANGELOG.md"
OPERABILITY = ROOT / "docs" / "OPERABILITY.md"
ADR = ROOT / "docs" / "adr" / "legacy-postgresql-extension-retirement.md"
DOCTORING = ROOT / "docs" / "doctoring" / "legacy-postgresql-extension-retirement.md"


def _text(path: Path) -> str:
    """Read one required UTF-8 documentation surface."""
    return path.read_text(encoding="utf-8")


def test_operator_guide_documents_safe_execution_and_recovery() -> None:
    """Operators need preflight, bounded failure recovery, replay, and rollback."""
    text = _text(OPERABILITY)

    for required in (
        "03_cron_batch_retrieval.sql",
        "lock_timeout = '5s'",
        "DROP EXTENSION IF EXISTS http RESTRICT",
        "DROP EXTENSION IF EXISTS pg_cron RESTRICT",
        "gateway_retrieval_logs",
        "Fail-closed recovery",
        "idempotent",
        "Rollback boundary",
    ):
        assert required in text
    assert "Do not replace `RESTRICT` with `CASCADE`" in text


def test_architecture_and_adr_preserve_the_authority_boundary() -> None:
    """Durable architecture must separate DB cleanup from provider authority."""
    architecture = _text(ARCHITECTURE)
    adr = _text(ADR)

    assert "Legacy provider-extension retirement" in architecture
    assert "database-side provider networking" in architecture
    assert "shared_preload_libraries" in architecture
    assert "Status:** Proposed" in adr
    assert "Never use `CASCADE`" in adr
    assert "operator-owned functions" in adr


def test_readme_changelog_and_doctoring_expose_the_next_operator_action() -> None:
    """Entry points and evidence notes must direct safe migration behavior."""
    readme = _text(README)
    changelog = _text(CHANGELOG)
    doctoring = _text(DOCTORING)

    assert "Existing-volume extension retirement" in readme
    assert "docs/OPERABILITY.md" in readme
    assert "gateway_retrieval_logs" in readme
    assert "fail-closed legacy PostgreSQL extension retirement" in changelog
    assert "PostgreSQL Global Development Group. (2026)." in doctoring
    assert "Unsupported claims" in doctoring
