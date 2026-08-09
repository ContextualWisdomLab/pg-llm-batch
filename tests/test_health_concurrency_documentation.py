# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for concurrent standalone readiness probes."""

from pathlib import Path


AGENTS = Path("AGENTS.md")
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


def test_bounded_health_probe_admission_contract_is_authoritative() -> None:
    """Docs must define the resource ceiling and every worker-slot release path."""
    agents = _normalized(AGENTS)
    adr = _normalized(ADR)
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    required = (
        "maximum of 32 admitted readiness requests",
        "closed before a worker thread or database check starts",
        "released after request completion or thread-start failure",
        "CWE-400",
        "socketserver — A framework for network servers",
    )
    for document in (adr, doctoring):
        for phrase in required:
            assert phrase in document

    assert "32 admitted readiness requests" in agents
    assert "excess connections" in agents
    assert "before worker or database work" in agents
    assert "release every admission slot" in agents
    assert "bounded concurrent readiness probes" in changelog.lower()
    assert "32" in changelog
