# SPDX-License-Identifier: Apache-2.0
"""Discoverability contract for canonical product documentation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CANONICAL_LINK_TARGETS = (
    "ARCHITECTURE.md",
    "SECURITY.md",
    "docs/product/PRD.md",
    "docs/product/TRD.md",
    "docs/product/API_CONTRACT.md",
    "docs/architecture/UML.md",
    "docs/architecture/ERD.md",
    "docs/THREAT_MODEL.md",
    "docs/TEST_STRATEGY.md",
    "docs/OPERABILITY.md",
    "docs/RELEASE_ACCEPTANCE.md",
    "docs/TRACEABILITY.md",
    "docs/adr/README.md",
    "docs/DOCUMENTATION_FITNESS.md",
)


def test_readme_indexes_canonical_documentation_authority() -> None:
    """README must link buyers and operators directly to canonical authorities."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in CANONICAL_LINK_TARGETS:
        assert f"]({target})" in readme, target
