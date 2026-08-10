# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for operation-span failure status."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRD = ROOT / "docs/product/TRD.md"
THREAT_MODEL = ROOT / "docs/THREAT_MODEL.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_operation_span_error_status_overlay_is_canonical_and_private() -> None:
    """ACTIVE-PR #106 must be classified without promoting it to shipped behavior."""
    trd = _normalized(TRD)
    threat_model = _normalized(THREAT_MODEL)
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    for phrase in (
        "active-pr #106",
        "statuscode.error",
        "without a description",
        "success status unset",
        "telemetry failure",
    ):
        assert phrase in trd, phrase

    for phrase in (
        "active-pr #106",
        "span status",
        "without a description",
        "exception messages",
        "telemetry failure",
    ):
        assert phrase in threat_model, phrase

    assert "operation span error status" in traceability
    assert "active-pr #106" in traceability
    assert "#106" in fitness
    assert "operation span" in fitness
