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
        "NIST SP 800-53",
        "Release 5.2.0",
        "NIST SP 800-218",
        "APA 7",
    )
    for phrase in required_phrases:
        assert phrase in text
