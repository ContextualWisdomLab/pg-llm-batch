# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for isolated restore-target service identity."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/postgres-restore-target-isolation.md")
ADR = Path("docs/adr/0021-postgres-restore-target-isolation.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_restore_target_docs_record_isolation_and_citation_contract() -> None:
    """Operators must name two distinct libpq services before restore."""
    documents = (_normalized(DOCTORING), _normalized(ADR))
    for document in documents:
        assert "live_service_name" in document
        assert "restore_service_name" in document
        assert "pg_restore" in document
        assert "isolated" in document
        assert "dsn" in document
        assert "tenant_scope" in document or "tenant scope" in document
        assert "package_capability" not in document or "false" in document
        assert "800-34" in document
        assert "800-53" in document
        assert "cwe-669" in document
        assert "0021" in document
        assert "postgresql 18" in document
