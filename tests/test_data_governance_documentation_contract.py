# SPDX-License-Identifier: Apache-2.0
"""Contracts for canonical privacy and data-governance documentation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_GOVERNANCE = "docs/DATA_GOVERNANCE.md"


def _read(path: str) -> str:
    """Read one UTF-8 repository document."""
    return (ROOT / path).read_text(encoding="utf-8")


def test_data_governance_is_canonical_and_release_gated() -> None:
    """Acquisition diligence must not depend on scattered privacy prose."""
    assert (ROOT / DATA_GOVERNANCE).is_file()

    readme = _read("README.md")
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")
    release = _read("docs/RELEASE_ACCEPTANCE.md")

    assert DATA_GOVERNANCE in readme
    assert "Data governance / privacy" in fitness
    assert DATA_GOVERNANCE in traceability
    assert "data governance" in release.lower()


def test_data_governance_separates_package_and_host_authority() -> None:
    """Privacy controls must preserve useful payloads while keeping authority explicit."""
    governance = _read(DATA_GOVERNANCE)
    lower = governance.lower()

    for phrase in (
        "data classification",
        "provider credential",
        "prompt",
        "provider result",
        "tenant_scope",
        "purpose-bound",
        "blanket masking",
        "retention",
        "erasure",
        "opentelemetry",
        "protected-main",
        "active-pr",
        "host-owned",
        "package-owned",
    ):
        assert phrase in lower, phrase

    assert "must not log" in lower or "never log" in lower
    assert "raw provider response" in lower or "provider response bodies" in lower


def test_product_requirements_bind_data_governance_authority() -> None:
    """Product and technical requirements must point to the governance owner."""
    prd = _read("docs/product/PRD.md").lower()
    trd = _read("docs/product/TRD.md").lower()

    assert DATA_GOVERNANCE.lower() in prd
    assert "purpose-bound" in prd
    assert "retention" in prd
    assert "host-owned" in prd

    assert DATA_GOVERNANCE.lower() in trd
    assert "data classification" in trd
    assert "retention" in trd
    assert "host-owned" in trd
