# SPDX-License-Identifier: Apache-2.0
"""Authoritative documentation contracts for redacted public readiness."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/public-healthz-readiness.md")
ADR = Path("docs/adr/0014-public-healthz-readiness.md")
CHANGELOG = Path("CHANGELOG.md")
AGENTS = Path("AGENTS.md")


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


def test_public_healthz_component_names_use_fixed_allow_list():
    """Docs must forbid arbitrary local component names at the HTTP boundary."""
    doctoring = _normalized(DOCTORING)
    adr = _normalized(ADR)
    changelog = _normalized(CHANGELOG)
    agents = _normalized(AGENTS)

    required_phrase = "fixed required-component allow-list"
    for document in (doctoring, adr, agents):
        assert required_phrase in document

    assert "unrecognized component names" in changelog.lower()


def test_health_query_timeout_boundary_is_authoritative():
    """Docs must preserve the bounded PostgreSQL statement-timeout contract."""
    doctoring = _normalized(DOCTORING)
    adr = _normalized(ADR)
    changelog = _normalized(CHANGELOG)
    agents = _normalized(AGENTS)

    for document in (doctoring, adr):
        assert "statement_timeout" in document
        assert "transaction-local" in document
        assert "4,000 milliseconds" in document
        assert "not an end-to-end deadline" in document
        assert "PostgreSQL 18" in document

    assert "statement timeout" in changelog.lower()
    assert "transaction-local" in agents
    assert "statement_timeout" in agents


def test_malformed_public_readiness_fails_closed_authoritatively():
    """Authoritative docs must forbid truth coercion at the public probe boundary."""
    doctoring = _normalized(DOCTORING)
    adr = _normalized(ADR)
    changelog = _normalized(CHANGELOG)
    agents = _normalized(AGENTS)

    for document in (doctoring, adr, agents):
        assert "non-coercive" in document
        assert "malformed readiness" in document
        assert "HTTP 503" in document

    assert "malformed readiness" in changelog.lower()
    assert "truth coercion" in changelog.lower()


def test_public_healthz_omits_runtime_fingerprint_authoritatively():
    """Public-probe docs must forbid stdlib/Python version disclosure."""
    doctoring = _normalized(DOCTORING)
    adr = _normalized(ADR)
    changelog = _normalized(CHANGELOG)

    for document in (doctoring, adr):
        assert "Server header" in document
        assert "Python version" in document
        assert "BaseHTTPRequestHandler" in document

    assert "server header" in changelog.lower()
    assert "python version" in changelog.lower()


def test_healthz_listener_network_exposure_is_explicit_authoritatively():
    """Docs must cover the secure default, explicit container opt-in, and library boundary."""
    doctoring = _normalized(DOCTORING)
    adr = _normalized(ADR)
    changelog = _normalized(CHANGELOG)
    agents = _normalized(AGENTS)

    for document in (doctoring, adr, agents):
        assert "127.0.0.1" in document
        assert "0.0.0.0" in document
        assert "explicit" in document.lower()
        assert "container" in document.lower()

    assert "serve_healthz(dsn)" in agents
    assert "library" in agents.lower()

    assert "loopback" in changelog.lower()
    assert "explicit" in changelog.lower()
    assert "container" in changelog.lower()


def test_contributor_contract_preserves_healthz_redaction_boundary():
    """Contributor guidance must prevent local diagnostics from becoming public."""
    agents = _normalized(AGENTS)

    assert "HTTP readiness confidentiality" in agents
    assert "check_health()" in agents
    assert "public_health_report()" in agents
    assert "diagnostic detail" in agents
    assert "Never serialize the detailed local report directly" in agents


def test_public_healthz_references_are_recorded_in_apa_style():
    """Doctoring must retain the reviewed primary and security references."""
    doctoring = _normalized(DOCTORING)

    assert "MITRE. (2026)." in doctoring
    assert "CWE-209: Generation of Error Message Containing Sensitive Information" in doctoring
    assert "Kubernetes Authors. (2026)." in doctoring
    assert "Configure liveness, readiness and startup probes" in doctoring
    assert "Fielding, R., Nottingham, M., & Reschke, J. (2022)." in doctoring
    assert "RFC 9111: HTTP caching" in doctoring
    assert "PostgreSQL Global Development Group. (2026)." in doctoring
    assert "Client connection defaults" in doctoring