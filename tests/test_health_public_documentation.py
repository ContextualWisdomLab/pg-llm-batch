# SPDX-License-Identifier: Apache-2.0
"""Authoritative documentation contracts for redacted public readiness."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/public-healthz-readiness.md")
ADR = Path("docs/adr/0014-public-healthz-readiness.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Return Markdown with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_public_healthz_security_boundary_is_authoritative():
    """Operator docs must distinguish local detail from public readiness."""
    doctoring = _normalized(DOCTORING)
    adr = _normalized(ADR)
    changelog = _normalized(CHANGELOG)

    required_contracts = (
        "local operator diagnostics",
        "public /healthz",
        "component and is_ready",
        "diagnostic detail",
        "Cache-Control: no-store",
        "CWE-209",
        "RFC 9111",
        "Kubernetes",
        "not authentication",
        "rollback",
    )
    for contract in required_contracts:
        assert contract in doctoring
        assert contract in adr

    assert "redact" in changelog.lower()
    assert "/healthz" in changelog
    assert "diagnostic" in changelog.lower()


def test_public_healthz_references_are_recorded_in_apa_style():
    """Doctoring must retain the reviewed primary and security references."""
    doctoring = _normalized(DOCTORING)

    assert "MITRE. (2026)." in doctoring
    assert "CWE-209: Generation of Error Message Containing Sensitive Information" in doctoring
    assert "Kubernetes Authors. (2026)." in doctoring
    assert "Configure liveness, readiness and startup probes" in doctoring
    assert "Fielding, R., Nottingham, M., & Reschke, J. (2022)." in doctoring
    assert "RFC 9111: HTTP caching" in doctoring
