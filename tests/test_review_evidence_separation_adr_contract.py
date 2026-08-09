# SPDX-License-Identifier: Apache-2.0
"""Regression contract for semantic-review and infrastructure-evidence separation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = "docs/automation/ADR-0004-review-evidence-separation.md"
ADR_INDEX_TARGET = "../automation/ADR-0004-review-evidence-separation.md"


def test_review_evidence_separation_is_a_durable_indexed_adr() -> None:
    """Infrastructure failures must not become synthetic source-code findings."""
    adr_path = ROOT / ADR_PATH
    assert adr_path.is_file(), f"missing review evidence separation ADR: {ADR_PATH}"

    index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
    assert f"]({ADR_INDEX_TARGET})" in index

    traceability = (ROOT / "docs/TRACEABILITY.md").read_text(encoding="utf-8")
    assert ADR_PATH in traceability

    adr = adr_path.read_text(encoding="utf-8").lower()
    for phrase in (
        "status: active-pr",
        "semantic source review",
        "infrastructure or policy blocker",
        "abstain",
        "must not become a source-code finding",
        "exact contributor head",
        "live base",
        "independent approval",
        "failure and recovery",
        "verification",
        "rollback and supersession",
    ):
        assert phrase in adr, phrase
