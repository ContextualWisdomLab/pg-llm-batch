# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for persisted virtual JSONL integrity."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"
TRD = ROOT / "docs/product/TRD.md"
DATA_GOVERNANCE = ROOT / "docs/DATA_GOVERNANCE.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_virtual_payload_integrity_gap_has_canonical_owner() -> None:
    """Issue #124 must be planned without claiming persistence hardening is shipped."""
    prd = _normalized(PRD)
    trd = _normalized(TRD)
    governance = _normalized(DATA_GOVERNANCE)
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    for phrase in (
        "persisted virtual jsonl payload integrity",
        "issue #124",
        "planned",
        "malformed persisted payload",
        "before provider i/o",
    ):
        assert phrase in prd, phrase

    for phrase in (
        "persisted virtual jsonl payload integrity",
        "issue #124",
        "planned",
        "llm_batch_file_payloads",
        "fail closed",
    ):
        assert phrase in trd, phrase

    for phrase in (
        "persisted virtual jsonl payload",
        "issue #124",
        "provider disclosure",
        "fail closed",
    ):
        assert phrase in governance, phrase

    assert "persisted virtual jsonl payload integrity" in traceability
    assert "planned #124" in traceability
    assert "virtual jsonl payload integrity" in fitness
    assert "#124" in fitness
