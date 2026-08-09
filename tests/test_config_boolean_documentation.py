# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for malformed boolean configuration fallback."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/config-boolean-defaults.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Return Markdown text with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_boolean_fallback_contract_is_authoritative() -> None:
    """Operator docs must preserve non-coercive declared-default fallback."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    assert "malformed boolean" in doctoring.lower()
    assert "declared default" in doctoring.lower()
    assert "false-default" in doctoring.lower()
    assert "com_config" in doctoring
    assert "rollback" in doctoring.lower()
    assert "Python Software Foundation. (2026)." in doctoring
    assert "Truth value testing" in doctoring
    assert "malformed boolean configuration" in changelog.lower()
