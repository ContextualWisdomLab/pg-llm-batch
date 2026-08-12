# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for fail-closed provider batch-status evidence."""

from pathlib import Path

DOCTORING = Path("docs/doctoring/http-425-too-early-retries.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_batch_status_shape_validation_is_authoritative() -> None:
    """Docs must name status/count shape, non-negative counts, and consistency."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "invalidbatchstatuspayload" in document
        assert "request_counts" in document
        assert "non-negative integer" in document
        assert "completed + failed" in document
        assert "non-empty status string" in document
