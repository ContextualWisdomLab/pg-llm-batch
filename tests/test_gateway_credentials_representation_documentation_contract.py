# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for provider credential representations."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_CONTRACT = ROOT / "docs/product/API_CONTRACT.md"
THREAT_MODEL = ROOT / "docs/THREAT_MODEL.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_gateway_credentials_representation_gap_is_canonical_and_bounded() -> None:
    """Issue #128 must be documented without claiming general serialization safety."""
    api = _normalized(API_CONTRACT)
    threat = _normalized(THREAT_MODEL)
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    for phrase in (
        "gatewaycredentials",
        "api_key",
        "representation",
        "planned #128",
        "not arbitrary serialization",
    ):
        assert phrase in api, phrase

    for phrase in (
        "credential representation",
        "api_key",
        "planned #128",
        "repr",
        "serialization",
    ):
        assert phrase in threat, phrase

    for phrase in (
        "provider credential representation confidentiality",
        "planned #128",
        "gatewaycredentials",
    ):
        assert phrase in traceability, phrase

    for phrase in (
        "provider credential representation",
        "planned #128",
        "gatewaycredentials",
    ):
        assert phrase in fitness, phrase
