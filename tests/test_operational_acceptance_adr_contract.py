# SPDX-License-Identifier: Apache-2.0
"""Regression contract for protected-main operational-acceptance governance."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = "docs/automation/ADR-0005-protected-main-operational-acceptance.md"
ADR_INDEX_TARGET = "../automation/ADR-0005-protected-main-operational-acceptance.md"


def test_protected_main_operational_acceptance_is_a_durable_indexed_decision() -> None:
    """Source merge must hand off to protected-main proof before incident/release closure."""
    adr_path = ROOT / ADR_PATH
    assert adr_path.is_file(), f"missing operational acceptance ADR: {ADR_PATH}"

    index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
    assert f"]({ADR_INDEX_TARGET})" in index

    traceability = (ROOT / "docs/TRACEABILITY.md").read_text(encoding="utf-8")
    assert ADR_PATH in traceability
    assert "protected-main operational acceptance" in traceability.lower()

    release_acceptance = (ROOT / "docs/RELEASE_ACCEPTANCE.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "protected main",
        "operational",
        "post-merge",
        "rollback",
    ):
        assert phrase in release_acceptance.lower(), phrase

    adr = adr_path.read_text(encoding="utf-8").lower()
    for phrase in (
        "status: active-pr",
        "source merge",
        "protected main",
        "operational acceptance",
        "fresh evidence",
        "rollback",
        "supersession",
        "read-only dependency",
    ):
        assert phrase in adr, phrase
