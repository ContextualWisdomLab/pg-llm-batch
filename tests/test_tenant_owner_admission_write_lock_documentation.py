# SPDX-License-Identifier: Apache-2.0
"""Owner-instruction contract for the lifecycle-outbox admission/write lock fence."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OWNER_INSTRUCTIONS = (
    REPOSITORY_ROOT / "AGENTS.md",
    REPOSITORY_ROOT / "CLAUDE.md",
)


def _normalized(path: Path) -> str:
    """Return one owner instruction with insignificant whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_owner_instructions_preserve_admission_to_write_lock_fence() -> None:
    """Owner guidance must keep DDL from racing live admission and the INSERT."""
    for path in OWNER_INSTRUCTIONS:
        document = _normalized(path)
        lowered = document.lower()
        assert "ROW EXCLUSIVE" in document
        assert "admission" in lowered
        assert "insert" in lowered
        assert "ddl" in lowered
        assert "caller transaction" in lowered
