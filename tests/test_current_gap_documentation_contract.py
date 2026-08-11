# SPDX-License-Identifier: Apache-2.0
"""Keep newly discovered product/security gaps visible in canonical documentation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    """Read one repository document as UTF-8 text."""
    return (ROOT / path).read_text(encoding="utf-8")


def test_prd_tracks_current_unshipped_gap_queue() -> None:
    """Bind current active/planned gaps to one product-authority section."""
    prd = _read("docs/product/PRD.md")
    active_targets = prd.split("## 6. Active product targets", 1)[1].split(
        "## 7. Non-goals", 1
    )[0]

    for marker in (
        "#101",
        "Issue #98",
        "Issue #99",
        "Issue #100",
        "Issue #102",
        "Issue #108",
        "Issue #109",
    ):
        assert marker in active_targets, marker

    assert "direct-SQL provider" in active_targets
    assert "automatic provider reconciliation" in active_targets
    assert "shared default PostgreSQL credential" in active_targets
    assert "container" in active_targets and "reproduc" in active_targets.lower()
    assert "non-finite" in active_targets
    assert "endpoint-qualified" in active_targets
    assert "single authoritative" in active_targets


def test_trd_keeps_legacy_sql_http_outside_provider_authority() -> None:
    """Document the SQL retriever retirement and its safe replacement boundary."""
    trd = _read("docs/product/TRD.md")
    provider_section = trd.split("## 4. Provider HTTP requirements", 1)[1].split(
        "## 5. Configuration", 1
    )[0]

    for phrase in (
        "#101",
        "pg_cron",
        "pgsql-http",
        "local batch UUID",
        "provider remote batch",
        "BatchAPIClient",
        "DurableBatchAPIClient",
    ):
        assert phrase in provider_section, phrase

    reliability_section = trd.split("## 9. Reliability and recovery requirements", 1)[1].split(
        "## 10. CI", 1
    )[0]
    assert "Issue #102" in reliability_section
    assert "automatic provider reconciliation" in reliability_section
    assert "distributed exactly-once" in reliability_section


def test_trd_tracks_tokenizer_and_release_version_authority_gaps() -> None:
    """Keep endpoint tokenizer and release-version authority gaps explicit."""
    trd = _read("docs/product/TRD.md")
    for phrase in (
        "Issue #108",
        "endpoint-qualified tokenizer",
        "Issue #109",
        "single authoritative version",
    ):
        assert phrase in trd, phrase


def test_fitness_and_traceability_do_not_hide_new_gap_owners() -> None:
    """Keep the maturity snapshot and traceability aligned with live gap owners."""
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")

    for marker in (
        "#101",
        "Issue #98",
        "Issue #99",
        "Issue #100",
        "Issue #102",
        "Issue #108",
        "Issue #109",
    ):
        assert marker in fitness, marker
    for marker in ("#101", "#98", "#99", "#100", "#102", "#108", "#109"):
        assert marker in traceability, marker


def test_new_packaging_and_compatibility_gaps_have_canonical_owners() -> None:
    """Track the newest packaging, compatibility, and quality-tool gaps end to end."""
    prd = _read("docs/product/PRD.md")
    trd = _read("docs/product/TRD.md")
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")

    active_targets = prd.split("## 6. Active product targets", 1)[1].split(
        "## 7. Non-goals", 1
    )[0]
    for phrase in (
        "Issue #112",
        "py.typed",
        "Issue #113",
        "Requires-Python",
        "#114",
        "uv toolchain",
        "Issue #115",
        "quality tools",
    ):
        assert phrase in active_targets, phrase

    for phrase in (
        "Issue #112",
        "py.typed",
        "Issue #113",
        "Requires-Python",
        "ACTIVE-PR #114",
        "uv toolchain",
        "Issue #115",
        "quality tools",
    ):
        assert phrase in trd, phrase

    for marker in ("Issue #112", "Issue #113", "#114", "Issue #115"):
        assert marker in fitness, marker
    for marker in ("#112", "#113", "#114", "#115"):
        assert marker in traceability, marker


def test_cli_argv_security_and_privacy_gaps_have_canonical_owners() -> None:
    """Keep prompt-content and credential-bearing DSN argv gaps explicit end to end."""
    prd = _read("docs/product/PRD.md")
    trd = _read("docs/product/TRD.md")
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")

    active_targets = prd.split("## 6. Active product targets", 1)[1].split(
        "## 7. Non-goals", 1
    )[0]
    for phrase in (
        "Issue #116",
        "count-tokens",
        "prompt content",
        "process argv",
        "Issue #117",
        "credential-bearing PostgreSQL DSNs",
    ):
        assert phrase in active_targets, phrase

    for phrase in (
        "Issue #116",
        "count-tokens",
        "prompt content",
        "process argv",
        "Issue #117",
        "credential-bearing PostgreSQL DSN",
        "before libpq",
    ):
        assert phrase in trd, phrase

    for marker in ("Issue #116", "Issue #117"):
        assert marker in fitness, marker
    for marker in ("#116", "#117"):
        assert marker in traceability, marker


def test_postgres_image_supply_chain_gap_has_canonical_owner() -> None:
    """Keep the PostgreSQL image dependency-reproducibility gap distinct from component image work."""
    prd = _read("docs/product/PRD.md")
    trd = _read("docs/product/TRD.md")
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")

    for document in (prd, trd, fitness):
        for phrase in (
            "Issue #118",
            "PostgreSQL image",
            "pg_tiktoken",
        ):
            assert phrase in document, phrase

    for phrase in (
        "#118",
        "PostgreSQL image",
        "docker/postgres/Dockerfile",
        "pg_tiktoken",
    ):
        assert phrase in traceability, phrase


def test_sql_retirement_and_reconciliation_reach_architecture_and_operations() -> None:
    """Keep the retired network authority and replacement seam explicit end to end."""
    architecture = _read("ARCHITECTURE.md")
    threat_model = _read("docs/THREAT_MODEL.md")
    operability = _read("docs/OPERABILITY.md")
    adr_index = _read("docs/adr/README.md")

    active_overlay = architecture.split("## 7. Active-PR overlay", 1)[1].split(
        "## 8. Architecture invariants", 1
    )[0]
    for phrase in ("#101", "direct-SQL", "Issue #102", "reconciliation"):
        assert phrase in active_overlay, phrase

    for phrase in ("pg_cron", "pgsql-http", "#101", "Issue #102"):
        assert phrase in threat_model, phrase

    for phrase in (
        "#101",
        "Issue #102",
        "direct-SQL",
        "provider remote batch",
        "finite",
        "reconciliation",
    ):
        assert phrase in operability, phrase

    feature_decisions = adr_index.split("## Feature decisions carried by active implementation PRs", 1)[1].split(
        "## ADR content contract", 1
    )[0]
    for phrase in ("#101", "direct-SQL", "Issue #102", "reconciliation"):
        assert phrase in feature_decisions, phrase


def test_database_timeout_gap_has_canonical_owner() -> None:
    """Track package-owned PostgreSQL wait budgets as PLANNED reliability work."""
    prd = _read("docs/product/PRD.md")
    trd = _read("docs/product/TRD.md")
    operability = _read("docs/OPERABILITY.md")
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")

    active_targets = prd.split("## 6. Active product targets", 1)[1].split(
        "## 7. Non-goals", 1
    )[0]
    for document in (active_targets, trd, operability, fitness):
        for phrase in (
            "Issue #122",
            "PostgreSQL",
            "connection",
            "timeout",
        ):
            assert phrase in document, phrase

    for phrase in (
        "#122",
        "Package-owned PostgreSQL",
        "connect_timeout",
        "statement_timeout",
    ):
        assert phrase in traceability, phrase


def test_postgres_transport_security_gap_has_canonical_owner() -> None:
    """Bind the transport-security gap to one decision plus product discovery."""
    prd = _read("docs/product/PRD.md")
    adr_index = _read("docs/adr/README.md")
    decision = _read("docs/adr/postgresql-transport-security.md")

    active_targets = prd.split("## 6. Active product targets", 1)[1].split(
        "## 7. Non-goals", 1
    )[0]
    for phrase in (
        "Issue #123",
        "PostgreSQL transport",
        "sslmode",
        "verify-full",
        "postgresql-transport-security.md",
    ):
        assert phrase in active_targets, phrase

    assert "](postgresql-transport-security.md)" in adr_index
    assert "Issue #123" in adr_index

    for phrase in (
        "Status:** PLANNED",
        "Issue #123",
        "sslmode",
        "verify-full",
        "verify-ca",
        "channel_binding=require",
        "No ad-hoc DSN rewriting",
        "Rollback and recovery",
        "PostgreSQL 18 documentation: SSL support",
    ):
        assert phrase in decision, phrase
