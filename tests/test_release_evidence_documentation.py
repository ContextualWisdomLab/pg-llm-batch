# SPDX-License-Identifier: Apache-2.0
"""Documentation contract for reproducible release acceptance."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0003-reproducible-release-evidence.md"
DOCTORING = ROOT / "docs" / "doctoring" / "reproducible-release-evidence.md"


def test_release_evidence_adr_separates_acceptance_from_publication() -> None:
    text = ADR.read_text(encoding="utf-8")

    assert "two clean exact-head builds" in text
    assert "SOURCE_DATE_EPOCH" in text
    assert "does not publish" in text
    assert "does not attest" in text
    assert "independent approval" in text


def test_release_evidence_doctoring_defines_bounded_operator_evidence() -> None:
    text = DOCTORING.read_text(encoding="utf-8")

    required = (
        "release-manifest.json",
        "SHA-256",
        "exactly one wheel",
        "exactly one source distribution",
        "regular non-symlink",
        "14 days",
        "SLSA v1.2",
        "APA 7",
    )
    for phrase in required:
        assert phrase in text


def test_release_evidence_doctoring_rejects_stale_stacked_base_proof() -> None:
    text = DOCTORING.read_text(encoding="utf-8")

    required = (
        "current stacked base",
        "GitHub-generated merge commit",
        "stale-base",
        "retarget",
        "integrated main",
    )
    for phrase in required:
        assert phrase in text
