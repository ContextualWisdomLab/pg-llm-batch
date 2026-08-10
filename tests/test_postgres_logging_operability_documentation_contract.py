# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for PostgreSQL logging operability."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"
TRD = ROOT / "docs/product/TRD.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for bounded section assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def _issue_entry(text: str, issue_number: int) -> str:
    """Return the level-three-heading section that owns a planned issue."""
    match = re.search(
        rf"^### [^\n]*\(issue #{issue_number}\)[^\n]*\n(?P<body>.*?)(?=^### |\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"missing Issue #{issue_number} canonical entry"
    return " ".join(match.group(0).lower().split())


def test_postgres_logging_operability_follow_up_is_canonical_and_planned() -> None:
    """Issue #120 must be bounded separately from ACTIVE-PR #119 privacy work."""
    prd = PRD.read_text(encoding="utf-8")
    trd = TRD.read_text(encoding="utf-8")
    fitness = _normalized(FITNESS)
    traceability = _normalized(TRACEABILITY)

    for document in (prd, trd):
        entry = _issue_entry(document, 120)
        for phrase in (
            "planned",
            "container-native",
            "storage-bounded",
            "#119",
            "retention",
        ):
            assert phrase in entry, phrase

    for text in (fitness, traceability):
        for phrase in (
            "issue #120",
            "planned",
            "container-native",
            "storage-bounded",
            "#119",
        ):
            assert phrase in text, phrase
