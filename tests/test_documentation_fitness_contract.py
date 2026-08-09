# SPDX-License-Identifier: Apache-2.0
"""Contracts for the repository's canonical product documentation authority."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DOCUMENTATION = (
    "ARCHITECTURE.md",
    "docs/DOCUMENTATION_FITNESS.md",
    "docs/product/PRD.md",
    "docs/product/TRD.md",
    "docs/product/API_CONTRACT.md",
    "docs/RELEASE_ACCEPTANCE.md",
    "docs/architecture/UML.md",
    "docs/architecture/ERD.md",
    "docs/THREAT_MODEL.md",
    "docs/TEST_STRATEGY.md",
    "docs/OPERABILITY.md",
    "docs/TRACEABILITY.md",
    "docs/adr/README.md",
    "docs/automation/ADR-0001-work-conserving-maintenance.md",
    "docs/automation/ADR-0002-evidence-identity-and-writer-lease.md",
)

FITNESS_STATES = (
    "PRESENT-CURRENT",
    "PRESENT-STALE",
    "PARTIAL",
    "MISSING",
    "NOT-APPLICABLE",
    "SUPERSEDED",
)

MATURITY_STATES = (
    "IMPLEMENTED-ON-PROTECTED-MAIN",
    "ACTIVE-PR",
    "PARTIAL",
    "ACCEPTED-ARCHITECTURE",
    "PLANNED",
    "RESEARCH-ONLY",
    "SUPERSEDED",
    "OUT-OF-SCOPE",
)


def _read(relative_path: str) -> str:
    """Read one required UTF-8 documentation file."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_canonical_documentation_graph_is_present() -> None:
    """A buyer must not need chat or PR-body archaeology to reconstruct the product."""
    missing = [path for path in REQUIRED_DOCUMENTATION if not (ROOT / path).is_file()]
    assert missing == [], f"missing canonical documentation: {missing}"


def test_documentation_fitness_uses_closed_status_vocabularies() -> None:
    """Fitness and capability maturity must distinguish stale docs from unshipped work."""
    fitness = _read("docs/DOCUMENTATION_FITNESS.md")
    for state in FITNESS_STATES + MATURITY_STATES:
        assert state in fitness, state
    assert "protected main" in fitness.lower()
    assert "active pr" in fitness.lower()


def test_architecture_graphs_are_machine_readable_and_status_aware() -> None:
    """UML and ERD must be executable diagrams with explicit shipped-vs-active truth."""
    architecture = _read("ARCHITECTURE.md")
    uml = _read("docs/architecture/UML.md")
    erd = _read("docs/architecture/ERD.md")

    assert "protected-main as-built" in architecture.lower()
    assert "active-pr overlay" in architecture.lower()
    assert uml.count("```mermaid") >= 6
    assert erd.count("```mermaid") >= 1
    assert "IMPLEMENTED-ON-PROTECTED-MAIN" in erd
    assert "ACTIVE-PR" in erd
    assert "llm_remote_batch_jobs" in erd
    assert "llm_result_stream_checkpoints" in erd
    assert "llm_result_checkpoint_audit_events" in erd


def test_traceability_binds_requirements_to_live_repository_surfaces() -> None:
    """Requirements and decisions must point to source, schema, tests, or evidence."""
    traceability = _read("docs/TRACEABILITY.md")
    for repository_surface in (
        "pg_llm_batch/schema.sql",
        "pg_llm_batch/batch_api_client.py",
        "pg_llm_batch/durable_client.py",
        "pg_llm_batch/orchestrator.py",
        "pg_llm_batch/health.py",
        ".github/workflows/ci.yml",
        "SECURITY.md",
    ):
        assert repository_surface in traceability
    assert "exact contributor head" in traceability.lower()
    assert "live base" in traceability.lower()
    assert "independent" in traceability.lower()


def test_api_contract_separates_current_surface_from_active_targets() -> None:
    """Public compatibility promises must not silently promote open-PR APIs to shipped."""
    contract = _read("docs/product/API_CONTRACT.md")
    for phrase in (
        "IMPLEMENTED-ON-PROTECTED-MAIN",
        "ACTIVE-PR",
        "BatchAPIClient",
        "DurableBatchAPIClient",
        "semantic versioning",
        "deprecation",
        "schema",
        "CLI",
    ):
        assert phrase.lower() in contract.lower()


def test_release_acceptance_requires_exact_integrated_evidence() -> None:
    """Release documentation must bind publication to integrated evidence and rollback."""
    release = _read("docs/RELEASE_ACCEPTANCE.md")
    for phrase in (
        "exact integrated protected head",
        "independent",
        "100%",
        "SBOM",
        "provenance",
        "rollback",
        "migration",
        "operational acceptance",
        "CHANGELOG",
    ):
        assert phrase.lower() in release.lower()


def test_automation_adrs_capture_work_conservation_and_writer_lease() -> None:
    """Maintenance behavior must be durable repository governance, not chat-only policy."""
    work_conserving = _read(
        "docs/automation/ADR-0001-work-conserving-maintenance.md"
    )
    evidence = _read(
        "docs/automation/ADR-0002-evidence-identity-and-writer-lease.md"
    )

    for phrase in (
        "no-early-stop",
        "branch rotation",
        "double exit sweep",
        "prompt",
        "documentation",
    ):
        assert phrase in work_conserving.lower()
    for phrase in (
        "writer lease",
        "exact contributor head",
        "live base",
        "synthetic",
        "independent approval",
        "read-only dependency",
    ):
        assert phrase in evidence.lower()
