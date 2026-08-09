# SPDX-License-Identifier: Apache-2.0
"""Contracts for the repository's canonical product documentation authority."""

from __future__ import annotations

import argparse
import ast
import re
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
    """Read one required UTF-8 repository file."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _section(text: str, start_heading: str, end_heading: str) -> str:
    """Return one explicitly bounded Markdown section."""
    start = text.index(start_heading) + len(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]


def _code_bullets(section: str) -> set[str]:
    """Extract simple one-code-span Markdown bullets as a normalized set."""
    return set(re.findall(r"^- `([^`]+)`\s*$", section, flags=re.MULTILINE))


def _package_root_exports() -> set[str]:
    """Read the literal package-root ``__all__`` contract directly from source."""
    tree = ast.parse(_read("pg_llm_batch/__init__.py"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            value = ast.literal_eval(node.value)
            assert isinstance(value, list)
            assert all(isinstance(item, str) for item in value)
            return set(value)
    raise AssertionError("pg_llm_batch.__all__ literal is missing")


def _parser_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Return one parser's declared subcommand choices."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _cli_commands() -> set[str]:
    """Build the CLI and return its exact top-level and nested config commands."""
    from pg_llm_batch.cli import build_parser

    top_level = _parser_choices(build_parser())
    commands = set(top_level) - {"config"}
    config_choices = _parser_choices(top_level["config"])
    commands.update(f"config {name}" for name in config_choices)
    return commands


def _entity_block(section: str, entity_name: str) -> str:
    """Return one Mermaid ERD entity block from a bounded section."""
    match = re.search(
        rf"^\s*{re.escape(entity_name)}\s*\{{(?P<body>.*?)^\s*\}}",
        section,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing ERD entity: {entity_name}"
    return match.group("body")


def _assert_text_order(text: str, phrases: tuple[str, ...]) -> None:
    """Require canonical prose/diagram tokens to appear in one declared order."""
    cursor = -1
    for phrase in phrases:
        next_cursor = text.find(phrase, cursor + 1)
        assert next_cursor >= 0, f"missing ordered phrase: {phrase}"
        assert next_cursor > cursor
        cursor = next_cursor


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
    """UML and ERD must structurally bind shipped and active persistence claims."""
    architecture = _read("ARCHITECTURE.md")
    uml = _read("docs/architecture/UML.md")
    erd = _read("docs/architecture/ERD.md")

    assert "protected-main as-built" in architecture.lower()
    assert "active-pr overlay" in architecture.lower()
    assert uml.count("```mermaid") >= 6
    assert erd.count("```mermaid") >= 1

    protected = _section(
        erd, "## Protected-main persisted model", "## ACTIVE-PR persistence overlay"
    )
    active = _section(
        erd, "## ACTIVE-PR persistence overlay", "## Ownership and non-persistence boundaries"
    )
    assert "IMPLEMENTED-ON-PROTECTED-MAIN" in protected
    assert "ACTIVE-PR" not in protected.split("```mermaid", 1)[0]
    assert "llm_remote_batch_jobs" in protected
    assert "llm_result_stream_checkpoints" not in protected
    assert "llm_result_checkpoint_audit_events" not in protected
    assert "ACTIVE-PR" in active
    assert "llm_result_stream_checkpoints" in active
    assert "llm_result_checkpoint_audit_events" in active
    assert "llm_remote_batch_jobs" not in active


def test_remote_lifecycle_erd_matches_persisted_projection_and_identity() -> None:
    """The protected lifecycle ERD must expose all persisted fields and its unique key."""
    erd = _read("docs/architecture/ERD.md")
    protected = _section(
        erd, "## Protected-main persisted model", "## ACTIVE-PR persistence overlay"
    )
    remote = _entity_block(protected, "llm_remote_batch_jobs")
    for column in (
        "input_file_id",
        "batch_endpoint",
        "output_file_id",
        "error_file_id",
        "total_requests",
        "completed_requests",
        "failed_requests",
        "first_seen_at",
        "last_observed_at",
        "terminal_at",
        "updated_at",
    ):
        assert column in remote, column
    assert "(endpoint_alias, remote_batch_id)" in protected
    assert "composite unique" in protected.lower()


def test_checkpoint_replacement_chain_is_canonical_across_authorities() -> None:
    """Current replacement owners must not be mixed with stale checkpoint PR owners."""
    adr = _read("docs/adr/README.md")
    architecture = _read("ARCHITECTURE.md")
    prd = _read("docs/product/PRD.md")
    trd = _read("docs/product/TRD.md")

    active_overlay = _section(architecture, "## 7. Active-PR overlay", "## 8. Architecture invariants")
    for current in ("#92", "#94", "#95", "#96", "#97"):
        assert current in adr, current
        assert current in active_overlay, current
    for stale in ("#78", "#79", "#80", "#83", "#84"):
        assert stale not in active_overlay, stale
        assert re.search(rf"SUPERSEDED[^\n]*{re.escape(stale)}|{re.escape(stale)}[^\n]*SUPERSEDED", adr)

    prd_t5 = _section(prd, "### PRD-T5", "### PRD-T6")
    for current in ("#92", "#94", "#96", "#97"):
        assert current in prd_t5, current
    prd_t6 = _section(prd, "### PRD-T6", "### PRD-T7")
    assert "#95" in prd_t6
    trd_rel4 = _section(trd, "### TRD-REL4", "## 10. CI, evidence, and review requirements")
    for current in ("#94", "#96", "#97"):
        assert current in trd_rel4, current


def test_batch_preparation_docs_follow_production_persistence_order() -> None:
    """Operator and UML sequence claims must match prepare/assemble/persist ordering."""
    operability = _section(
        _read("docs/OPERABILITY.md"), "### Batch preparation", "### Remote batch lifecycle"
    )
    uml = _section(
        _read("docs/architecture/UML.md"),
        "## 2. Batch preparation sequence",
        "## 3. Provider request, retry, and response handoff",
    )
    expected = (
        "read queued requests",
        "count tokens",
        "partition",
        "persist payload document",
        "persist batch file",
        "persist jsonl lines",
        "assign queued requests",
        "update batch totals",
        "commit",
    )
    sequence_match = re.search(
        r"```mermaid\s*\nsequenceDiagram(?P<body>.*?)```",
        uml,
        flags=re.DOTALL,
    )
    assert sequence_match is not None, "missing batch preparation sequence diagram"
    _assert_text_order(operability.lower(), expected)
    _assert_text_order(sequence_match.group("body").lower(), expected)
    assert "rolls back the transaction" in operability.lower()


def test_uml_tracks_checkpoint_replacements_and_merge_revalidation() -> None:
    """UML must show the full live checkpoint chain and explicit merge/post-check authority."""
    uml = _read("docs/architecture/UML.md")
    checkpoint = _section(
        uml,
        "## 5. Result streaming and checkpoint overlay",
        "## 6. Health/readiness deployment sequence",
    )
    merge = _section(uml, "## 7. Evidence and merge authority", "## 8. Standalone and CWL composition")

    for current in ("#92", "#94", "#95", "#96", "#97"):
        assert current in checkpoint, current
    assert "SUPERSEDED" in checkpoint
    for phrase in (
        "merge execution",
        "open pr queue",
        "finding resolution",
        "branch protection",
        "live graph",
        "protected-main post-check",
    ):
        assert phrase in merge.lower(), phrase
    assert "synthetic merge ref/status-only evidence" in merge.lower()


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


def test_api_contract_matches_current_package_root_exports() -> None:
    """The documented protected package-root surface must equal source ``__all__``."""
    contract = _read("docs/product/API_CONTRACT.md")
    section = _section(
        contract,
        "## 3. Python package surface — IMPLEMENTED-ON-PROTECTED-MAIN",
        "### Python error compatibility",
    )
    assert _code_bullets(section) == _package_root_exports()


def test_api_contract_matches_current_cli_commands() -> None:
    """The documented protected CLI command set must equal the parser surface."""
    contract = _read("docs/product/API_CONTRACT.md")
    section = _section(
        contract,
        "## 4. CLI surface — IMPLEMENTED-ON-PROTECTED-MAIN",
        "### ACTIVE-PR CLI overlays",
    )
    assert _code_bullets(section) == _cli_commands()


def test_api_contract_separates_current_surface_from_active_targets() -> None:
    """Public compatibility promises must not silently promote open-PR APIs to shipped."""
    contract = _read("docs/product/API_CONTRACT.md")
    protected_python = _section(
        contract,
        "## 3. Python package surface — IMPLEMENTED-ON-PROTECTED-MAIN",
        "### Python error compatibility",
    )
    active_cli = _section(
        contract, "### ACTIVE-PR CLI overlays", "## 5. Provider HTTP contract"
    )
    assert "remain target interfaces" in protected_python
    assert "until their implementing branch reaches protected main" in protected_python
    assert "Issue #90" in active_cli
    assert "PLANNED" in active_cli
    assert "cancel" in active_cli
    for phrase in ("semantic versioning", "deprecation", "schema", "CLI"):
        assert phrase.lower() in contract.lower()


def test_operability_names_current_checkpoint_migration_replacement() -> None:
    """Operators must be directed to current migration owner #95, not superseded #80."""
    migration = _section(
        _read("docs/OPERABILITY.md"), "## Migration and rollback", "## Incident evidence"
    )
    assert "ACTIVE-PR #95" in migration
    assert "#80" in migration and "SUPERSEDED" in migration


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
