# SPDX-License-Identifier: Apache-2.0
"""Regression contract for cancellation capability maturity in public docs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_does_not_present_planned_cancellation_as_current_operation() -> None:
    """README retry guidance must not imply a cancellation API before it ships."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    fitness = (ROOT / "docs/DOCUMENTATION_FITNESS.md").read_text(encoding="utf-8").lower()

    assert "cancellation `post` operations are never retried" not in readme
    assert "upload and batch creation `post` operations are never retried" in readme
    assert "issue #90" in fitness
    assert "**planned**" in fitness
