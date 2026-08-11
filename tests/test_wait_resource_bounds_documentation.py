# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for bounded batch-wait resource controls."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/http-425-too-early-retries.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_wait_resource_controls_are_authoritative() -> None:
    """Operator docs must require finite positive poll and timeout durations."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "poll_interval_seconds" in document
        assert "timeout_seconds" in document
        assert "finite positive" in document
        assert "before credential" in document
