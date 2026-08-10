# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for provider-secret encryption policy."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ADR = "docs/adr/provider-secret-encryption-policy.md"


def _normalized(path: str) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join((ROOT / path).read_text(encoding="utf-8").lower().split())


def _level_three_section(path: str, heading_fragment: str) -> str:
    """Return one normalized level-three Markdown section by heading fragment."""
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(
        rf"^### [^\n]*{re.escape(heading_fragment)}[^\n]*\n(?P<body>.*?)(?=^### |^## |\Z)",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing section containing {heading_fragment!r} in {path}"
    return " ".join((match.group(0)).lower().split())


def test_secret_encryption_policy_gap_has_an_indexed_canonical_decision() -> None:
    """Issue #121 must have one detailed, indexed PLANNED architecture decision."""
    index = _normalized("docs/adr/README.md")
    adr = _normalized(ADR)

    assert "issue #121" in index
    assert "](provider-secret-encryption-policy.md)" in index

    for phrase in (
        "**status:** planned — issue #121",
        "provider-secret",
        "base64",
        "not encryption",
        "fernet",
        "encryption-required",
        "existing `is_encrypted = false` rows",
        "key rotation",
        "multifernet",
        "local/development",
        "not implemented on protected `main`",
    ):
        assert phrase in adr, phrase


def test_prd_and_trd_bind_issue_121_to_the_same_planned_policy() -> None:
    """PRD-T31 and TRD-C8 must carry the issue, maturity, and encryption boundary."""
    prd = _level_three_section("docs/product/PRD.md", "provider-secret encryption policy")
    trd = _level_three_section("docs/product/TRD.md", "provider-secret encryption policy")

    for section in (prd, trd):
        for phrase in (
            "issue #121",
            "planned",
            "base64",
            "not encryption",
            "fernet",
            "encryption-required",
            "key rotation",
            "docs/adr/provider-secret-encryption-policy.md",
        ):
            assert phrase in section, phrase


def test_secret_policy_does_not_overwrite_the_shipped_baseline() -> None:
    """The planned policy must remain compatible with documented protected-main behavior."""
    trd = _normalized("docs/product/TRD.md")
    threat = _normalized("docs/THREAT_MODEL.md")

    assert "secretstore supports fernet encryption when configured" in trd
    assert "base64 without a fernet key remains obfuscation, not encryption" in trd
    assert "base64 remains obfuscation rather than encryption" in threat
