# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for live-inspect recovery-receipt verification."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/postgres-recovery-receipt-verification.md")
ADR = Path("docs/adr/0020-postgres-recovery-receipt-verification.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_verification_docs_record_live_inspect_and_citation_contract() -> None:
    """Operators must re-inspect current bytes; exact-type objects are not provenance."""
    documents = (_normalized(DOCTORING), _normalized(ADR))
    for document in documents:
        assert "inspect_postgres_schema" in document
        assert "inspect_postgres_backup_artifact" in document
        assert "backup_artifact_path" in document
        assert "provenance" in document or "inspected" in document
        assert "exact-type" in document or "exact type" in document
        assert "package_capability" not in document or "false" in document
        assert "fips" in document
        assert "180-4" in document
        assert "800-53" in document
        assert "cwe-367" in document
        assert "pg_restore" in document
        assert "0020" in document
        assert "0018" not in document or "collision" in document
