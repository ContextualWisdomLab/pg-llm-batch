# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for readiness database-target authority."""

from pathlib import Path

DOCTORING = Path("docs/doctoring/public-healthz-readiness.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_health_database_target_authority_is_documented() -> None:
    """Readiness docs must reject ambient/invalid DSN selection before libpq."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "invalid postgres dsn" in document
        assert "non-string" in document
        assert "whitespace-only" in document
        assert "before psycopg" in document
        assert "libpq" in document
