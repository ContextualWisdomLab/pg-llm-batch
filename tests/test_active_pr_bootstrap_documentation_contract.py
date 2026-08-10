# SPDX-License-Identifier: Apache-2.0
"""Contracts binding the current bootstrap-authority ACTIVE-PR to canonical docs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    """Read one UTF-8 canonical document in normalized lowercase form."""
    return (ROOT / path).read_text(encoding="utf-8").lower()


def _active_pr_entry(text: str, pr_number: int) -> str:
    """Return the single Markdown list entry for one active pull request."""
    marker = f"- #{pr_number} "
    matches = [line for line in text.splitlines() if line.startswith(marker)]
    assert len(matches) == 1, (pr_number, matches)
    return matches[0]


def test_bootstrap_authority_overlay_tracks_exact_string_type_boundary() -> None:
    """PR #89's exact-string bootstrap authority must be durable and not shipped."""
    trd = _read("docs/product/TRD.md")
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")

    assert "active-pr" in trd and "#89" in trd
    assert "explicit postgres dsn" in trd
    assert "explicit fernet" in trd
    assert "exact string" in trd
    assert "non-string" in trd
    assert "environment fallback" in trd

    fitness_entry = _active_pr_entry(fitness, 89)
    assert "bootstrap" in fitness_entry and "precedence" in fitness_entry

    assert "| explicit bootstrap source precedence | active-pr #89 |" in traceability
    assert "protected main" in trd
