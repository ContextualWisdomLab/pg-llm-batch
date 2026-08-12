# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for descriptor-pinned release artifact verification."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_release_artifact_security_contract_is_authoritative_and_consistent() -> None:
    """Require operator, architecture, agent, and decision records for the boundary."""
    documents = {
        "agents": (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
        "claude": (ROOT / "CLAUDE.md").read_text(encoding="utf-8"),
        "architecture": (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8"),
        "adr": (
            ROOT
            / "docs/adr/0004-descriptor-pinned-release-artifact-verification.md"
        ).read_text(encoding="utf-8"),
        "doctoring": (
            ROOT / "docs/doctoring/release-artifact-descriptor-verification.md"
        ).read_text(encoding="utf-8"),
        "changelog": (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
    }

    combined = "\n".join(documents.values())
    required_contracts = (
        "descriptor-relative",
        "O_DIRECTORY",
        "O_NOFOLLOW",
        "O_NONBLOCK",
        "same open file description",
        "directory descriptor",
        "changed during verification",
        "fail closed",
        "CWE-367",
        "Python 3.14",
        "IEEE Std 1003.1-2024",
        "does not publish",
        "rollback",
    )
    for contract in required_contracts:
        assert contract in combined

    assert "pathname fallback" in documents["adr"]
    assert "Do not add or enable a pathname fallback" in documents["doctoring"]
    assert "version `0.1.0` remains unchanged" in documents["adr"].lower()
