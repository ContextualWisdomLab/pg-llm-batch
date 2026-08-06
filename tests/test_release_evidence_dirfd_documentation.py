# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for descriptor-bound release manifest writes."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0003-reproducible-release-evidence.md"
DOCTORING = ROOT / "docs" / "doctoring" / "reproducible-release-evidence.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def test_release_evidence_adr_governs_descriptor_bound_manifest_writes() -> None:
    """Require the architectural decision to state every path-security boundary."""
    text = ADR.read_text(encoding="utf-8")

    required = (
        "descriptor-relative",
        "`O_NOFOLLOW`",
        "`os.rename()`",
        "fails closed on unsupported platforms",
        "file and final parent directory",
        "temporary entry created by the current invocation",
        "after the function returns",
    )
    for phrase in required:
        assert phrase in text


def test_release_evidence_doctoring_explains_operations_and_recovery() -> None:
    """Require beginner-readable operator verification and failure triage."""
    text = DOCTORING.read_text(encoding="utf-8")

    required = (
        "directory descriptor",
        "descriptor-relative",
        "`O_DIRECTORY`",
        "`O_NOFOLLOW`",
        "`fsync()`",
        "unsupported platform",
        "owned temporary",
        "atomic replacement",
        "rollback",
    )
    for phrase in required:
        assert phrase in text


def test_release_evidence_documents_authoritative_toctou_references() -> None:
    """Require current primary standards and CWE evidence in authoritative docs."""
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in (ADR, DOCTORING)
    )

    required = (
        "CWE-367",
        "Python 3.14 documentation",
        "The Open Group Base Specifications Issue 8",
        "IEEE Std 1003.1-2024",
    )
    for phrase in required:
        assert phrase in combined


def test_release_evidence_changelog_records_descriptor_bound_security_fix() -> None:
    """Require buyer-visible release notes without a version or release claim."""
    text = CHANGELOG.read_text(encoding="utf-8")

    assert "descriptor-relative" in text
    assert "time-of-check/time-of-use" in text
    assert "version `0.1.0` remains unchanged" in text
