# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for the OpenTelemetry packaging gap."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"
TRD = ROOT / "docs/product/TRD.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_opentelemetry_optional_dependency_gap_is_canonical_and_planned() -> None:
    """Issue #107 must be visible without implying a shipped package extra."""
    prd = _normalized(PRD)
    trd = _normalized(TRD)
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    for phrase in (
        "issue #107",
        "opentelemetry optional dependency",
        "planned",
        "base package",
    ):
        assert phrase in prd, phrase

    for phrase in (
        "trd-pkg5",
        "issue #107",
        "opentelemetry-api",
        "optional extra",
        "base dependency set",
    ):
        assert phrase in trd, phrase

    assert "opentelemetry optional dependency and live conformance" in traceability
    assert "planned #107" in traceability
    assert "issue #107" in fitness
    assert "opentelemetry optional dependency" in fitness
