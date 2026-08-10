# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contracts for structured exception evidence."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_CONTRACT = ROOT / "docs/product/API_CONTRACT.md"
TRD = ROOT / "docs/product/TRD.md"
THREAT_MODEL = ROOT / "docs/THREAT_MODEL.md"
DATA_GOVERNANCE = ROOT / "docs/DATA_GOVERNANCE.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_structured_error_evidence_overlay_is_canonical_and_bounded() -> None:
    """ACTIVE-PR #105 must be documented without immutability overclaims."""
    api = _normalized(API_CONTRACT)
    trd = _normalized(TRD)
    threat_model = _normalized(THREAT_MODEL)
    governance = _normalized(DATA_GOVERNANCE)
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    for phrase in (
        "pgl l m batch error".replace(" ", ""),
        "gatewayerror",
        "constructor-time shallow snapshot",
        "active-pr #105",
        "not immutable",
    ):
        assert phrase in api, phrase

    for phrase in (
        "structured exception evidence",
        "constructor-time shallow snapshot",
        "outer caller-owned mapping",
        "nested mutable values",
        "not a durable audit record",
        "active-pr #105",
    ):
        assert phrase in trd, phrase

    for phrase in (
        "caller-owned mapping",
        "structured exception evidence",
        "shallow snapshot",
        "live exception object",
        "not an audit record",
        "active-pr #105",
    ):
        assert phrase in threat_model, phrase

    for phrase in (
        "structured exception evidence",
        "constructor-time shallow snapshot",
        "nested mutable values",
        "not an audit record",
        "active-pr #105",
    ):
        assert phrase in governance, phrase

    assert "structured error evidence snapshot" in traceability
    assert "active-pr #105" in traceability
    assert "structured error evidence" in fitness
    assert "#105" in fitness
