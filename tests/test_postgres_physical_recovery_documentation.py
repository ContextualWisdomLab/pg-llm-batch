# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for bounded physical/WAL/PITR recovery profiles."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/postgres-physical-pitr-profile.md")
ADR = Path("docs/adr/0019-postgres-physical-pitr-profile.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_physical_pitr_docs_record_operator_and_citation_contract() -> None:
    """Operators must see isolation, WAL, time-flow, and non-capability steps."""
    documents = (_normalized(DOCTORING), _normalized(ADR))
    for document in documents:
        assert "isolated_target_prepared" in document
        assert "wal_archive_required" in document
        assert "package_capability_claim" in document
        assert "point-in-time" in document or "point in time" in document
        assert "pg_basebackup" in document
        assert "swanson" in document
        assert "nist" in document
        assert "postgresql" in document
        assert "continuous archiving" in document
