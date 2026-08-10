# SPDX-License-Identifier: Apache-2.0
"""Documentation fitness contract for the active BatchRequest hardening slice."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, start_heading: str, end_heading: str) -> str:
    """Return one explicitly bounded Markdown section."""
    start = text.index(start_heading) + len(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]


def test_batch_request_runtime_hardening_is_visible_in_active_pr_fitness() -> None:
    """Canonical fitness must not omit the current public BatchRequest hardening owner."""
    fitness = (ROOT / "docs/DOCUMENTATION_FITNESS.md").read_text(encoding="utf-8")
    active = _section(fitness, "### ACTIVE-PR", "### PLANNED")

    assert "#104" in active
    assert "BatchRequest" in active
    assert "runtime" in active.lower()


def test_batch_request_runtime_hardening_stays_bound_to_api_contract() -> None:
    """Fitness navigation and compatibility authority must identify the same active owner."""
    contract = (ROOT / "docs/product/API_CONTRACT.md").read_text(encoding="utf-8")
    active_boundary = _section(
        contract,
        "### ACTIVE-PR `BatchRequest` runtime boundary (#104)",
        "### Resource ownership",
    )

    assert "exact runtime field typing" in active_boundary
    assert "Rejected values must not be exported" in active_boundary
