# SPDX-License-Identifier: Apache-2.0
"""Regression contract for durable canonical-documentation authority."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = "docs/automation/ADR-0003-canonical-documentation-authority.md"


def test_canonical_documentation_authority_is_a_durable_indexed_adr() -> None:
    """Documentation truth and maturity rules must not live only in chat or PR prose."""
    adr_path = ROOT / ADR_PATH
    assert adr_path.is_file(), f"missing canonical documentation authority ADR: {ADR_PATH}"

    index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
    assert ADR_PATH in index

    adr = adr_path.read_text(encoding="utf-8").lower()
    for phrase in (
        "status: active-pr",
        "protected main",
        "active pr",
        "documentation fitness",
        "chat",
        "machine-checkable",
        "rollback",
        "supersession",
    ):
        assert phrase in adr, phrase
