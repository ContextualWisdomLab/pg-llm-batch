# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for TokenCounter resource authority."""

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


def test_configured_resource_ceiling_boundary_is_authoritative() -> None:
    """Docs must preserve every exact-positive configured ceiling before PostgreSQL."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "per_batch" in document
        assert "per_request" in document
        assert "max_records_per_file" in document
        assert "max_bytes_per_file" in document
        assert "max_files_per_job" in document
        assert "exact positive integer" in document
        assert "before postgresql" in document
