# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for the batch-wide physical JSONL line budget."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    """Read one authoritative repository document as UTF-8 text."""
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_public_and_contributor_contracts_name_the_physical_line_limit():
    """Public and contributor guidance expose the exact constructor control."""
    for path in (
        "README.md",
        "docs/result-streaming.md",
        "AGENTS.md",
        "CLAUDE.md",
    ):
        content = _text(path)
        assert "max_jsonl_physical_lines" in content, path
        assert "blank" in content.lower(), path


def test_architecture_and_change_history_record_batch_wide_line_accounting():
    """Architecture and change history preserve the cross-file budget boundary."""
    for path in ("ARCHITECTURE.md", "CHANGELOG.md"):
        normalized = " ".join(_text(path).lower().split())
        assert "batch-wide physical line" in normalized, path
        assert "result and error" in normalized, path


def test_authoritative_decision_and_doctoring_record_resource_exhaustion_sources():
    """ADR and doctoring cite current resource-exhaustion authorities in APA form."""
    for path in (
        "docs/adr/0005-bounded-jsonl-result-streaming.md",
        "docs/doctoring/bounded-jsonl-result-streaming.md",
    ):
        content = _text(path)
        normalized = " ".join(content.lower().split())
        assert "max_jsonl_physical_lines" in content, path
        assert "cwe-400" in normalized, path
        assert "api4:2023" in normalized, path
        assert "blank" in normalized, path
