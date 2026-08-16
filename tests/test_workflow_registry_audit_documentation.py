# SPDX-License-Identifier: Apache-2.0
"""Operator-document contracts for the read-only workflow registry audit."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs/doctoring/workflow-registry-audit.md"
ADR = ROOT / "docs/adr/0021-workflow-registry-audit.md"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_operator_docs_tell_the_next_safe_action() -> None:
    """A buyer must see the installable command, exit codes, and no-mutation rule."""
    documents = {
        "doctoring": _normalized(DOCTORING),
        "adr": _normalized(ADR),
        "changelog": _normalized(CHANGELOG),
        "readme": _normalized(README),
        "architecture": _normalized(ARCHITECTURE),
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
        "slsa v1.0",
        "torres-arias",
        "rfc 3339",
        "klyne",
        "adr 0021",
    ):
        assert token in doctoring, token


def test_workflow_registry_audit_adr_avoids_open_recovery_number_collision() -> None:
    """Keep this decision off 0016-0020, which open recovery PRs already claim."""
    adr_dir = ROOT / "docs/adr"
    assert ADR.is_file()
    assert not (adr_dir / "0016-workflow-registry-audit.md").exists()
    heading = ADR.read_text(encoding="utf-8").splitlines()[0]
    assert heading == "# ADR 0021: Read-only exact-SHA workflow registry audit"
