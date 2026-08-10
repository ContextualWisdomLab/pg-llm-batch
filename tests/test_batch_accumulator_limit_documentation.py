# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for ``BatchAccumulator`` resource ceilings."""

from pathlib import Path

DOCTORING = Path("docs/doctoring/token-counter-buffer-boundary.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_accumulator_resource_ceiling_contract_is_documented() -> None:
    """Docs must reject truthiness fallback for explicit/configured ceilings."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "max_records" in document
        assert "max_bytes" in document
        assert "exact positive integer" in document
        assert "explicit zero" in document
        assert "configured default" in document
