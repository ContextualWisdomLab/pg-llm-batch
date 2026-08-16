# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the data-governance overlay."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE = REPOSITORY_ROOT / "docs" / "DATA_GOVERNANCE.md"
FITNESS = REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md"


def _read(path: Path) -> str:
    """Return one Markdown document as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_data_governance_maps_classes_retention_and_deletion_limits() -> None:
    """A buyer must see data classes, owners, retention, and what the package will not delete."""
    text = " ".join(_read(GOVERNANCE).split())
    assert "llm_requests" in text
    assert "com_secrets" in text
    assert "tenant_scope" in text
    assert "authorized business payloads" in text.lower()
    assert "Do not mask" in text or "do not mask" in text
    assert "retention" in text.lower()
    assert "deletion" in text.lower()
    assert "host owns" in text.lower() or "embedding host owns" in text.lower()


def test_data_governance_cites_privacy_and_control_authorities() -> None:
    """Doctoring must cite current privacy-control publications in APA 7th."""
    text = " ".join(_read(GOVERNANCE).split())
    assert "NIST Special Publication 800-53" in text
    assert "https://doi.org/10.6028/NIST.SP.800-53r5" in text
    assert "ISO/IEC 27701" in text or "ISO/IEC 29100" in text


def test_fitness_inventory_tracks_the_data_governance_overlay() -> None:
    """The fitness matrix must stop calling data governance merely planned."""
    fitness = _read(FITNESS)
    assert "docs/DATA_GOVERNANCE.md" in fitness
    assert "| Data governance | PLANNED |" not in fitness
