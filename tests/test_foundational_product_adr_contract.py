# SPDX-License-Identifier: Apache-2.0
"""Require durable ADRs for the shipped product's foundational boundaries."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_INDEX = ROOT / "docs/adr/README.md"

FOUNDATIONAL_ADRS = (
    "docs/adr/foundation-postgresql-authority.md",
    "docs/adr/foundation-provider-http-boundary.md",
    "docs/adr/foundation-standalone-composition.md",
    "docs/adr/foundation-lifecycle-observation.md",
)

REQUIRED_SECTIONS = (
    "## Status and maturity",
    "## Context and decision drivers",
    "## Alternatives considered",
    "## Decision",
    "## Consequences and non-goals",
    "## Failure and recovery",
    "## Security, privacy, and governance impact",
    "## Compatibility and migration",
    "## Verification and acceptance",
    "## Rollback and supersession",
)


def test_foundational_product_adrs_are_indexed_and_complete() -> None:
    """Protected-main architectural choices must have durable decision records."""
    index = ADR_INDEX.read_text(encoding="utf-8")
    for relative_path in FOUNDATIONAL_ADRS:
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        assert f"({Path(relative_path).name})" in index, relative_path
        text = path.read_text(encoding="utf-8")
        assert "IMPLEMENTED-ON-PROTECTED-MAIN" in text, relative_path
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{relative_path}: missing {section}"


def test_foundational_adrs_cover_distinct_product_authorities() -> None:
    """The minimum ADR set must cover database, provider, composition, and lifecycle."""
    combined = "\n".join(
        (ROOT / relative_path).read_text(encoding="utf-8").lower()
        for relative_path in FOUNDATIONAL_ADRS
    )
    for phrase in (
        "postgresql",
        "disk-free",
        "provider",
        "single-attempt",
        "standalone",
        "embedding host",
        "llm_remote_batch_jobs",
        "observation order",
    ):
        assert phrase in combined, phrase
