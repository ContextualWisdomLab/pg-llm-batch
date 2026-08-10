# SPDX-License-Identifier: Apache-2.0
"""Contracts keeping canonical docs aligned with current security-overlay PRs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    """Read one UTF-8 repository document in normalized lowercase form."""
    return (ROOT / path).read_text(encoding="utf-8").lower()


def _section(text: str, heading: str, next_heading: str) -> str:
    """Return one canonical Markdown section bounded by adjacent headings."""
    start = text.index(heading.lower())
    end = text.index(next_heading.lower(), start)
    return text[start:end]


def test_health_listener_overlay_tracks_exact_input_and_port_boundary() -> None:
    """PR #70's current listener-input boundary must be durable documentation."""
    trd = _read("docs/product/TRD.md")
    operability = _read("docs/OPERABILITY.md")
    threat = _read("docs/THREAT_MODEL.md")

    for document in (trd, operability, threat):
        assert "#70" in document
        assert "c0" in document
        assert "del" in document
        assert "1..65535" in document
    assert "non-boolean integer" in trd
    assert "exact" in trd and "host" in trd


def test_health_listener_overlay_tracks_no_shell_container_authority() -> None:
    """PR #70's container command path must remain data, never shell syntax."""
    trd = _read("docs/product/TRD.md")
    operability = _read("docs/OPERABILITY.md")
    threat = _read("docs/THREAT_MODEL.md")

    for document in (trd, operability, threat):
        assert "#70" in document
        assert "exec-form" in document
        assert "shell" in document
        assert "8080" in document
    assert "pg_llm_batch_health_port" in threat
    assert "explicit" in operability and "override" in operability


def test_gateway_url_overlay_distinguishes_main_normalization_from_exact_input_target() -> None:
    """PR #71 must not be backported into the protected-main URL authority claim."""
    trd = _read("docs/product/TRD.md")
    threat = _read("docs/THREAT_MODEL.md")
    gateway = _section(trd, "### trd-h1", "### trd-h2")

    assert "protected main" in gateway
    assert "stringif" in gateway
    assert "strip" in gateway
    assert "surrounding whitespace" in gateway
    assert "active-pr" in gateway and "#71" in gateway
    assert "exact string" in gateway
    assert "before secret lookup" in gateway
    assert "trailing" in gateway and "slash" in gateway
    assert "after exact validation" in gateway

    assert "#71" in threat
    assert "stringif" in threat and "strip" in threat
    assert "surrounding whitespace" in threat
    assert "before secret lookup" in threat
    assert "active-pr" in threat


def test_provider_error_overlay_tracks_body_independence_and_exception_privacy() -> None:
    """PR #71 must document status-first errors and malformed-success privacy."""
    trd = _read("docs/product/TRD.md")
    governance = _read("docs/DATA_GOVERNANCE.md")
    threat = _read("docs/THREAT_MODEL.md")

    for document in (trd, governance, threat):
        assert "#71" in document
        assert "provider-error confidentiality" in document
    assert "status" in trd and "before" in trd and "body" in trd
    assert "malformed successful" in governance
    assert "cause" in governance and "context" in governance
    assert "malformed successful" in threat


def test_secret_store_overlay_tracks_malformed_persistence_and_wrong_key_boundary() -> None:
    """PR #87's current fail-closed decode/decrypt contract must be explicit."""
    trd = _read("docs/product/TRD.md")
    governance = _read("docs/DATA_GOVERNANCE.md")
    threat = _read("docs/THREAT_MODEL.md")

    for document in (trd, governance, threat):
        assert "#87" in document
        assert "base64" in document
        assert "wrong" in document and "fernet" in document and "key" in document
        assert "configerror" in document
    assert "utf-8" in trd
    assert "cause" in threat and "context" in threat


def test_compose_overlay_tracks_complete_published_service_allowlist() -> None:
    """PR #91 must constrain the entire published-port set, not two spot checks."""
    trd = _read("docs/product/TRD.md")
    operability = _read("docs/OPERABILITY.md")
    threat = _read("docs/THREAT_MODEL.md")

    for document in (trd, operability, threat):
        assert "#91" in document
        assert "allow-list" in document
        assert "5432" in document
        assert "8080" in document
    assert "third" in trd and "published" in trd and "service" in trd
