# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for provider-secret encryption policy."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _normalized(path: str) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join((ROOT / path).read_text(encoding="utf-8").lower().split())


def test_secret_encryption_policy_gap_is_owned_end_to_end() -> None:
    """Issue #121 must remain explicit without claiming the policy is shipped."""
    documents = {
        "prd": _normalized("docs/product/PRD.md"),
        "trd": _normalized("docs/product/TRD.md"),
        "threat": _normalized("docs/THREAT_MODEL.md"),
        "governance": _normalized("docs/DATA_GOVERNANCE.md"),
        "operability": _normalized("docs/OPERABILITY.md"),
        "fitness": _normalized("docs/DOCUMENTATION_FITNESS.md"),
        "traceability": _normalized("docs/TRACEABILITY.md"),
    }

    for name, text in documents.items():
        assert "#121" in text, name

    for phrase in (
        "provider-secret encryption",
        "planned",
        "base64",
        "fernet",
        "encryption-required",
    ):
        assert phrase in documents["prd"], phrase
        assert phrase in documents["trd"], phrase

    for phrase in (
        "base64",
        "not encryption",
        "encryption-required",
        "key rotation",
    ):
        assert phrase in documents["threat"], phrase
        assert phrase in documents["governance"], phrase

    assert "planned #121" in documents["traceability"]
    assert "issue #121" in documents["fitness"]
