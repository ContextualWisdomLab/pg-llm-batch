# SPDX-License-Identifier: Apache-2.0
"""Contracts for licensing and IP evidence required by acquisition diligence."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    """Read one UTF-8 repository file."""
    return (ROOT / path).read_text(encoding="utf-8")


def test_acquisition_licensing_authority_is_discoverable_and_consistent() -> None:
    """Buyers must be able to trace outbound licensing, provenance, and notices."""
    authority = ROOT / "docs/LICENSING_AND_IP.md"
    assert authority.is_file(), "missing canonical licensing/IP acquisition authority"

    text = authority.read_text(encoding="utf-8")
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    release = _read("docs/RELEASE_ACCEPTANCE.md")
    pyproject = _read("pyproject.toml")
    notice = _read("NOTICE")

    assert "Licensing / IP / third-party notices" in fitness
    assert "license/notice" in release.lower()

    assert 'license = "Apache-2.0"' in pyproject
    assert 'license-files = ["LICENSE", "NOTICE"]' in pyproject
    assert "Apache License" in _read("LICENSE")
    assert "Copyright (c) ContextualWisdomLab" in notice

    for phrase in (
        "Apache-2.0",
        "NOTICE",
        "third-party",
        "provenance",
        "ownership",
        "SBOM",
        "release",
        "due diligence",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_licensing_authority_does_not_overclaim_third_party_clearance() -> None:
    """Repository declarations must remain evidence, not a substitute for legal review."""
    text = _read("docs/LICENSING_AND_IP.md").lower()
    assert "does not replace legal review" in text
    assert "verify" in text and "dependency" in text


def test_notice_does_not_call_lgpl_dependencies_permissive() -> None:
    """NOTICE must not contradict its own LGPL dependency declaration."""
    notice = _read("NOTICE")
    assert "LGPL" in notice
    assert "depends only on\npermissively-licensed components" not in notice
    assert "respective license terms" in notice


def test_notice_accounts_for_configured_psycopg_binary_distribution() -> None:
    """The notice must expose the binary extra and its release-specific bundled libraries."""
    pyproject = _read("pyproject.toml")
    notice = _read("NOTICE")
    assert '"psycopg[binary]>=' in pyproject
    assert "psycopg-binary" in notice
    assert "bundled client libraries" in notice
    assert "release SBOM" in notice


def test_release_acceptance_fails_closed_on_unverified_licensing_evidence() -> None:
    """Release authority must include licensing/IP as a non-substitutable evidence gate."""
    release = _read("docs/RELEASE_ACCEPTANCE.md").lower()
    assert "docs/licensing_and_ip.md" in release
    assert "licensing/ip" in release
    assert "dependency license" in release
    assert "unverified ownership" in release
