# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation coverage for recently accepted buyer-visible gaps."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for bounded semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_recent_buyer_gaps_are_visible_in_product_targets() -> None:
    """Recent accepted issues must remain explicit PLANNED product targets."""
    prd = _normalized(PRD)

    required = {
        "#124": "virtual jsonl payload integrity",
        "#125": "lifecycle diagnostic confidentiality",
        "#126": "pg_tiktoken extension authority",
        "#127": "durable lifecycle status",
        "#128": "provider credential representation confidentiality",
        "#129": "batch-key authority",
        "#130": "tenant-scoped content-bearing work state",
        "#131": "token-counting diagnostic confidentiality",
        "#132": "generic validation diagnostic confidentiality",
        "#134": "runtime config/secret provisioning authority",
        "#136": "provider-side batch file lifecycle",
    }
    for issue, phrase in required.items():
        assert issue in prd, issue
        assert phrase in prd, phrase

    for issue in required:
        issue_pos = prd.index(issue)
        window = prd[max(0, issue_pos - 180): issue_pos + 520]
        assert "planned" in window, issue

    assert "active-pr #87" in prd
    assert "active-pr #53" in prd
    assert "active-pr #71" in prd

    provisioning_pos = prd.index("#134")
    provisioning = prd[max(0, provisioning_pos - 180): provisioning_pos + 1_500]
    assert "active-pr #86" in provisioning
    assert "#87" in provisioning
    assert "#89" in provisioning


def test_latest_buyer_gaps_are_traceable_and_fitness_classified() -> None:
    """Issues #132, #134, and #136 must not live only in PRD or issue tracker."""
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    for document in (traceability, fitness):
        assert "#132" in document
        assert "generic validation diagnostic confidentiality" in document
        assert "#134" in document
        assert "runtime config/secret provisioning authority" in document
        assert "#136" in document
        assert "provider-side batch file lifecycle" in document

    provisioning_pos = traceability.index("#134")
    provisioning = traceability[max(0, provisioning_pos - 240): provisioning_pos + 1_500]
    assert "planned" in provisioning
    assert "com_config" in provisioning
    assert "com_secrets" in provisioning
    assert "least-privilege" in provisioning
    assert "#86" in provisioning
    assert "#87" in provisioning
    assert "#89" in provisioning

    lifecycle_pos = traceability.index("#136")
    lifecycle = traceability[max(0, lifecycle_pos - 240): lifecycle_pos + 1_600]
    assert "planned" in lifecycle
    assert "active-pr #71" in lifecycle
    assert "expires_after" in lifecycle
    assert "output_expires_after" in lifecycle
    assert "delete" in lifecycle
