# SPDX-License-Identifier: Apache-2.0
"""Public compatibility promises must be explicit before release governance relies on them."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPATIBILITY_POLICY = REPOSITORY_ROOT / "docs" / "COMPATIBILITY.md"


def test_public_compatibility_policy_names_buyer_visible_contract_boundaries() -> None:
    """Compatibility policy must cover public, durable, security, and release authority."""
    assert COMPATIBILITY_POLICY.is_file(), (
        "docs/COMPATIBILITY.md must define the package-wide compatibility and "
        "deprecation contract before compatibility can be claimed"
    )

    text = COMPATIBILITY_POLICY.read_text(encoding="utf-8")
    lowered = text.lower()

    required_headings = (
        "# Compatibility and deprecation policy",
        "## Compatibility surface",
        "## Pre-1.0 versioning",
        "## Deprecation lifecycle",
        "## Security corrections",
        "## Durable data and rollback",
        "## Release evidence",
    )
    for heading in required_headings:
        assert heading in text, f"missing compatibility-policy heading: {heading}"

    required_contract_terms = (
        "pg_llm_batch.__all__",
        "command-line interface",
        "serialized evidence",
        "postgresql schema",
        "migration",
        "rollback",
        "exact source",
        "package",
        "release",
        "warning",
        "earliest removal version",
    )
    for term in required_contract_terms:
        assert term in lowered, f"compatibility policy omits required contract term: {term}"

    assert "security" in lowered
    assert "fail closed" in lowered or "fail-closed" in lowered
    assert "unsafe behavior" in lowered
    assert "credentials" in lowered
    assert "tenant" in lowered
    assert "dsn" in lowered
