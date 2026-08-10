# SPDX-License-Identifier: Apache-2.0
"""Contracts for current planned buyer-visible product gaps."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"


def _normalized() -> str:
    """Return normalized lower-case PRD content for section assertions."""
    return " ".join(PRD.read_text(encoding="utf-8").lower().split())


def test_current_buyer_gaps_are_planned_not_shipped() -> None:
    """Issues 108-111 must remain visible and dependency-bounded in the PRD."""
    prd = _normalized()

    expected = (
        ("prd-t18", "issue #108", "endpoint-qualified tokenizer", "planned", "#87", "#53"),
        ("prd-t19", "issue #109", "single authoritative version", "planned", "#57", "#53"),
        ("prd-t20", "issue #110", "http session ownership", "planned", "#71", "aclose"),
        ("prd-t21", "issue #111", "credential resolution concurrency", "planned", "#71", "#87"),
    )
    for phrases in expected:
        for phrase in phrases:
            assert phrase in prd, phrase

    implemented = prd.split("## 6. active product targets", 1)[0]
    for issue_number in ("issue #108", "issue #109", "issue #110", "issue #111"):
        assert issue_number not in implemented, issue_number
