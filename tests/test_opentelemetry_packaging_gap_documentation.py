# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for the OpenTelemetry packaging gap."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/product/PRD.md"
ADR = ROOT / "docs/adr/opentelemetry-optional-dependency.md"
ADR_INDEX = ROOT / "docs/adr/README.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_opentelemetry_optional_dependency_gap_is_canonical_and_planned() -> None:
    """Issue #107 must be visible without implying a shipped package extra."""
    prd = _normalized(PRD)
    adr = _normalized(ADR)
    index = _normalized(ADR_INDEX)
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    for phrase in (
        "issue #107",
        "opentelemetry optional dependency",
        "planned",
        "base package",
        "#57",
        "#106",
    ):
        assert phrase in prd, phrase

    for phrase in (
        "**status:** planned",
        "issue #107",
        "opentelemetry-api",
        "optional extra",
        "base package dependency set",
        "python 3.10, 3.12, and 3.14",
        "100%",
        "#57",
        "#106",
    ):
        assert phrase in adr, phrase

    assert "](opentelemetry-optional-dependency.md)" in index
    assert "issue #107" in index
    assert "planned first-class opentelemetry optional dependency" in index

    for phrase in (
        "opentelemetry optional dependency and live conformance",
        "planned #107",
        "opentelemetry-optional-dependency.md",
    ):
        assert phrase in traceability, phrase

    for phrase in (
        "issue #107",
        "opentelemetry optional dependency",
        "planned",
        "#57",
        "#106",
    ):
        assert phrase in fitness, phrase
