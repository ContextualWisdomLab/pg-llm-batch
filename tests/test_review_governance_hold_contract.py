# SPDX-License-Identifier: Apache-2.0
"""Regression contract for the current solo-maintainer review-governance hold."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_governance_preserves_code_owner_review_hold() -> None:
    """Canonical docs must not invent an unsatisfiable code-owner approval gate."""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8").lower()
    adr = (
        ROOT / "docs/automation/ADR-0004-review-evidence-separation.md"
    ).read_text(encoding="utf-8").lower()
    release = (ROOT / "docs/RELEASE_ACCEPTANCE.md").read_text(encoding="utf-8").lower()
    fitness = (ROOT / "docs/DOCUMENTATION_FITNESS.md").read_text(encoding="utf-8").lower()
    traceability = (ROOT / "docs/TRACEABILITY.md").read_text(encoding="utf-8").lower()

    assert "code-owner review gates — disabled (on hold)" in agents
    assert "single maintainer" in agents

    for document in (adr, release, fitness, traceability):
        assert "code-owner" in document
        assert "on hold" in document
        assert "where required" in document

    assert "must not be inferred as a universal merge requirement" in adr
    assert "do not re-enable" in release
    assert "solo-maintainer" in fitness
    assert "code-owner review hold" in traceability
