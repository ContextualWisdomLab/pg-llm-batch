# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for concurrent standalone readiness probes."""

from pathlib import Path


ADR = Path("docs/adr/0014-public-healthz-readiness.md")
DOCTORING = Path("docs/doctoring/public-healthz-readiness.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Return Markdown with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_concurrent_health_probe_contract_is_authoritative() -> None:
    """Docs must preserve independent probe progress under a blocked check."""
    adr = _normalized(ADR)
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    for document in (adr, doctoring):
        assert "independent readiness probes" in document
        assert "ThreadingMixIn" in document
        assert "serial" in document.lower()
        assert "Python Software Foundation. (2026)." in document
        assert "http.server — HTTP servers" in document

    assert "concurrent readiness probes" in changelog.lower()
