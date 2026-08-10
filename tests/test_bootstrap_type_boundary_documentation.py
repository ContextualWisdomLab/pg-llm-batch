# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for exact-string bootstrap authority inputs."""

from pathlib import Path

DOCTORING = Path("docs/doctoring/bootstrap-dsn-precedence.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_bootstrap_authority_documents_reject_non_string_explicit_values() -> None:
    """Both bootstrap authorities must document exact-string type validation."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, changelog):
        assert "non-string" in document
        assert "explicit postgres dsn" in document
        assert "explicit fernet" in document
        assert "before environment fallback" in document
