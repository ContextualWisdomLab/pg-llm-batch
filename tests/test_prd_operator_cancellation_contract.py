# SPDX-License-Identifier: Apache-2.0
"""Keep operator-cancellation maturity honest in the canonical PRD."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"


def _section(text: str, start_heading: str, end_heading: str) -> str:
    """Return one explicitly bounded Markdown section."""
    start = text.index(start_heading) + len(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]


def test_prd_does_not_claim_cli_cancellation_is_shipped() -> None:
    """Protected-main API cancellation must not be conflated with planned CLI cancel."""
    prd = PRD.read_text(encoding="utf-8")
    remote_workflow = _section(prd, "### PRD-R3", "### PRD-R4")
    active_targets = _section(prd, "## 6. Active product targets", "## 7. Non-goals")

    assert "BatchAPIClient" in remote_workflow
    assert "CLI commands" not in remote_workflow
    assert "Issue #90" in active_targets
    assert "PLANNED" in active_targets
    assert "cancel" in active_targets.lower()
