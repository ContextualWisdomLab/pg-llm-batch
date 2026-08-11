# SPDX-License-Identifier: Apache-2.0
"""Canonical PRD coverage for recently accepted buyer-visible gaps."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"


def _normalized_prd() -> str:
    """Return normalized lower-case PRD text for bounded semantic assertions."""
    return " ".join(PRD.read_text(encoding="utf-8").lower().split())


def test_recent_buyer_gaps_are_visible_in_product_targets() -> None:
    """Issues #124 through #129 must remain explicit PLANNED product targets."""
    prd = _normalized_prd()

    required = {
        "#124": "virtual jsonl payload integrity",
        "#125": "lifecycle diagnostic confidentiality",
        "#126": "pg_tiktoken extension authority",
        "#127": "durable lifecycle status",
        "#128": "provider credential representation confidentiality",
        "#129": "batch-key authority",
    }
    for issue, phrase in required.items():
        assert issue in prd, issue
        assert phrase in prd, phrase

    for issue in required:
        issue_pos = prd.index(issue)
        window = prd[max(0, issue_pos - 180): issue_pos + 480]
        assert "planned" in window, issue

    assert "active-pr #87" in prd
    assert "active-pr #53" in prd
    assert "active-pr #71" in prd
