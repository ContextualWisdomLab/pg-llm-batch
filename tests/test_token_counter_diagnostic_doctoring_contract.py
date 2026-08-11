# SPDX-License-Identifier: Apache-2.0
"""Doctoring contracts for token-counting diagnostic confidentiality."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs/doctoring/token-counting-diagnostic-confidentiality.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def test_token_counting_diagnostic_confidentiality_is_doctored() -> None:
    """The privacy repair must document its exact boundary and recovery contract."""
    assert DOCTORING.exists(), "missing token-counting diagnostic confidentiality doctoring"
    doctoring = " ".join(DOCTORING.read_text(encoding="utf-8").lower().split())
    changelog = " ".join(CHANGELOG.read_text(encoding="utf-8").lower().split())

    for phrase in (
        "finite package-owned diagnostic category",
        "lower-layer exception text",
        "undefinedfunction",
        "no python tokenizer fallback",
        "rollback",
        "postgresql 18",
        "apa 7",
    ):
        assert phrase in doctoring, phrase

    assert "token-counting diagnostic confidentiality" in changelog
