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
    ):
        assert marker in active_targets, marker

    assert "direct-SQL provider" in active_targets
    assert "automatic provider reconciliation" in active_targets
    assert "shared default PostgreSQL credential" in active_targets
    assert "container" in active_targets and "reproduc" in active_targets.lower()
    assert "non-finite" in active_targets


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


def test_fitness_and_traceability_do_not_hide_new_gap_owners() -> None:
    """Keep the maturity snapshot and traceability aligned with live gap owners."""
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    traceability = _read("docs/TRACEABILITY.md")

    for marker in ("#101", "Issue #98", "Issue #99", "Issue #100", "Issue #102"):
        assert marker in fitness, marker
    for marker in ("#101", "#98", "#99", "#100", "#102"):
        assert marker in traceability, marker


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
