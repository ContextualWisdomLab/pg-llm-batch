# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for bounded PostgreSQL logical restore."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/postgres-logical-restore.md")
ADR = Path("docs/adr/0016-postgres-logical-restore-seek.md")
CHANGELOG = Path("CHANGELOG.md")
ARCHITECTURE = Path("ARCHITECTURE.md")
README = Path("README.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_logical_restore_docs_record_seek_and_rollback_contract() -> None:
    """Operators must see the seek, trust, allowlist, and unsafe-mismatch steps."""
    documents = (
        _normalized(DOCTORING),
        _normalized(ADR),
        _normalized(CHANGELOG),
        _normalized(ARCHITECTURE),
        _normalized(README),
    )
    for document in documents:
        assert "source_superusers_trusted" in document
        assert "pgpassword" in document
        assert "pgservicefile" in document
        assert "single-transaction" in document
        assert "end-of-file" in document or "end of file" in document
        assert "not an authorization" in document
        assert "unsafe" in document
