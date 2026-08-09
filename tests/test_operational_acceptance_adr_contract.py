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


def test_merge_authority_diagram_runs_operational_acceptance_after_integration() -> None:
    """The UML must not depict post-merge acceptance before protected integration."""
    uml = (ROOT / "docs/architecture/UML.md").read_text(encoding="utf-8")
    section = uml.split("## 7. Evidence and merge authority", maxsplit=1)[1].split(
        "## 8. Standalone and CWL composition", maxsplit=1
    )[0]

    merge_to_main = "MERGE --> MAIN[Protected main exact integrated revision]"
    main_to_acceptance = "MAIN --> POST[Post-merge operational acceptance]"
    acceptance_to_closure = "POST --> ACCEPT[Operational acceptance evidence]"

    assert merge_to_main in section
    assert main_to_acceptance in section
    assert acceptance_to_closure in section
    assert section.index(merge_to_main) < section.index(main_to_acceptance)
    assert section.index(main_to_acceptance) < section.index(acceptance_to_closure)
