# SPDX-License-Identifier: Apache-2.0
"""Static contracts for the component and sequence UML overlay."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UML = REPOSITORY_ROOT / "docs" / "uml" / "component-and-sequence.md"
FITNESS = REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md"


def _read(path: Path) -> str:
    """Return one Markdown document as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_uml_shows_standalone_and_embedded_component_boundaries() -> None:
    """A buyer must see standalone operation and MSA embedding as co-equal."""
    text = _read(UML)
    assert "flowchart" in text or "C4Context" in text
    assert "sequenceDiagram" in text
    assert "DurableBatchAPIClient" in text
    assert "TenantDurableBatchAPIClient" in text
    assert "standalone" in text
    assert "contextual-orchestrator" in text
    assert "naruon" in text
    assert "set_config" in text


def test_fitness_inventory_tracks_the_uml_overlay() -> None:
    """The fitness matrix must stop calling UML merely planned."""
    fitness = _read(FITNESS)
    assert "docs/uml/component-and-sequence.md" in fitness
    assert "| UML/component/sequence views | PLANNED |" not in fitness
