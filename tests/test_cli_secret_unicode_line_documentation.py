# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for the CLI secret logical-line boundary."""

from pathlib import Path

DOCTORING = Path("docs/doctoring/cli-secret-input.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_secret_input_docs_name_non_lf_logical_line_separators() -> None:
    """Operator docs must make the complete one-line secret framing explicit."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "vertical tab" in document
        assert "form feed" in document
        assert "next line" in document
        assert "u+2028" in document
        assert "u+2029" in document
        assert "terminal lf/crlf" in document
