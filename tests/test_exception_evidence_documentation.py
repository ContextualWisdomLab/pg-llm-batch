# SPDX-License-Identifier: Apache-2.0
"""Documentation contract for structured exception evidence integrity."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs" / "doctoring" / "structured-error-evidence-integrity.md"


def test_structured_error_evidence_doctoring_records_assurance_boundary():
    """Doctoring must state snapshot limits and current assurance references."""
    text = DOCTORING.read_text(encoding="utf-8")

    required_phrases = (
        "constructor-time snapshot",
        "caller-owned mapping",
        "shallow snapshot",
        "not immutable",
        "ISO/IEC 27002:2022",
        "NIST SP 800-53 Rev. 5, Release 5.2.0",
        "https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final",
        "https://csrc.nist.gov/news/2025/nist-releases-revision-to-sp-800-53-controls",
        "NIST SP 800-218 Rev. 1",
        "SSDF Version 1.2",
        "https://csrc.nist.gov/pubs/sp/800/218/r1/ipd",
        "https://csrc.nist.gov/projects/ssdf/publications",
        "status verified 2026-08-12",
        "APA 7",
    )
    for phrase in required_phrases:
        assert phrase in text
