# SPDX-License-Identifier: Apache-2.0
"""Operator-document contracts for the read-only workflow registry audit."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs/doctoring/workflow-registry-audit.md"
ADR = ROOT / "docs/adr/0021-workflow-registry-audit.md"
PYPROJECT = ROOT / "pyproject.toml"


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_operator_docs_tell_the_next_safe_action() -> None:
    """The bounded owner docs must describe install, evidence, and no mutation."""
    documents = {
        "doctoring": _normalized(DOCTORING),
        "adr": _normalized(ADR),
    }

    for name, document in documents.items():
        assert "pg-llm-batch-workflow-audit" in document, name
        assert "active_absent_workflows" in document or "candidates" in document, name
        assert "dynamic/" in document or "platform-managed" in document, name

    doctoring = documents["doctoring"]
    for token in (
        "exit `0`",
        "exit `2`",
        "exit `1`",
        "do not disable",
        "https://api.github.com",
        "exact decoder",
        "nist sp 800-218",
        "https://slsa.dev/spec/v1.0/",
        "torres-arias",
        "rfc 3339",
        "klyne",
        "adr 0021",
        "documentation ownership",
    ):
        assert token in doctoring, token

    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert (
        'pg-llm-batch-workflow-audit = "pg_llm_batch.workflow_registry_audit:main"'
        in pyproject
    )


def test_workflow_registry_audit_adr_stays_proposed_and_collision_free() -> None:
    """Keep reserved ADR 0021 distinct until the detector reaches protected main."""
    adr_dir = ROOT / "docs/adr"
    assert ADR.is_file()
    heading = ADR.read_text(encoding="utf-8").splitlines()[0]
    assert heading == "# ADR 0021: Read-only exact-SHA workflow registry audit"
    adr = _normalized(ADR)
    assert "**status:** proposed" in adr
    assert "adr 0022" in adr
    assert not (adr_dir / "0021-postgres-restore-target-isolation.md").exists()
