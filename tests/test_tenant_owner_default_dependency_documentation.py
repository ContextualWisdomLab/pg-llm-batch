# SPDX-License-Identifier: Apache-2.0
"""Owner-instruction contract for omitted-default dependency identity."""

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


def test_owner_instructions_authenticate_default_dependency_identity() -> None:
    """Default deparse equality must not substitute for dependency identity."""
    for path in OWNER_INSTRUCTIONS:
        document = _normalized(path)
        lowered = document.lower()
        assert "pg_depend" in document
        assert "default" in lowered
        assert "dependency" in lowered
        assert "identity" in lowered
        assert "pg_get_expr" in document
        assert "before tenant binding" in lowered
