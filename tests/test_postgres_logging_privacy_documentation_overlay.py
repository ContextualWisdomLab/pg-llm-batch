# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for PostgreSQL logging privacy hardening."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"
TRD = ROOT / "docs/product/TRD.md"
THREAT_MODEL = ROOT / "docs/THREAT_MODEL.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_postgresql_logging_privacy_overlay_has_canonical_owners() -> None:
    """ACTIVE-PR #119 must be visible without being promoted to shipped behavior."""
    required = {
        PRD: (
            "active-pr #119",
            "postgresql logging privacy",
            "selective disclosure",
        ),
        TRD: (
            "active-pr #119",
            "pg_stat_statements",
            "pg_stat_activity",
        ),
        THREAT_MODEL: (
            "active-pr #119",
            "query text",
            "pg_read_all_stats",
        ),
        FITNESS: (
            "postgresql logging privacy",
            "active-pr #119",
        ),
        TRACEABILITY: (
            "postgresql logging privacy",
            "active-pr #119",
            "postgresql.conf.custom",
        ),
    }

    for path, phrases in required.items():
        normalized = _normalized(path)
        for phrase in phrases:
            assert phrase in normalized, f"{path}: {phrase}"
