# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for TokenCounter buffer resource authority."""

from pathlib import Path

DOCTORING = Path("docs/doctoring/token-counter-buffer-boundary.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_token_counter_buffer_type_boundary_is_authoritative() -> None:
    """Docs must preserve exact-integer validation before PostgreSQL acquisition."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "buffer_percentage" in document
        assert "exact integer" in document
        assert "0 through 50" in document
        assert "before postgresql" in document
