# SPDX-License-Identifier: Apache-2.0
"""Authoritative documentation contracts for durable result checkpoints."""

from pathlib import Path


def _text(path: str) -> str:
    """Read one authoritative UTF-8 project document with normalized spacing."""
    return " ".join(Path(path).read_text(encoding="utf-8").split())


def test_authoritative_documents_define_durable_checkpoint_contract() -> None:
    """Contributor and operator contracts agree on persistence boundaries."""
    contracts = {
        "AGENTS.md": (
            "PostgresBatchResultCheckpointStore",
            "save_in_transaction",
            "NOBYPASSRLS",
        ),
        "CLAUDE.md": (
            "PostgresBatchResultCheckpointStore",
            "expected_previous",
            "initial_checkpoint_race",
        ),
        "ARCHITECTURE.md": (
            "llm_result_stream_checkpoints",
            "compare-and-swap",
            "caller-owned transaction",
        ),
        "CHANGELOG.md": (
            "durable result-checkpoint store",
            "fail-closed rollback",
            "fresh bundled PostgreSQL image",
            "04_result_stream_checkpoints.sql",
        ),
        "docs/result-streaming.md": (
            "apply_result_checkpoint_schema",
            "save_in_transaction",
            "not a distributed exactly-once protocol",
        ),
        "docs/adr/0007-durable-result-checkpoint-store.md": (
            "Status: Accepted",
            "FOR UPDATE",
            "ON CONFLICT",
            "full-stream immutability",
        ),
        "docs/doctoring/durable-result-checkpoint-store.md": (
            "PostgreSQL 18",
            "NIST SP 800-53 Rev. 5",
            "Retrieved August 6, 2026",
            "04_result_stream_checkpoints.sql",
            "after the cron initialization script",
        ),
    }
    for path, required_phrases in contracts.items():
        content = _text(path)
        for phrase in required_phrases:
            assert phrase in content, f"{path} is missing {phrase!r}"


def test_doctoring_records_primary_sources_in_apa_7_style() -> None:
    """The assurance record cites current primary sources with stable details."""
    doctoring = _text("docs/doctoring/durable-result-checkpoint-store.md")
    required_references = (
        "National Institute of Standards and Technology. (2020).",
        "https://doi.org/10.6028/NIST.SP.800-53r5",
        "PostgreSQL Global Development Group. (n.d.).",
        "Explicit locking",
        "Row security policies",
    )
    for reference in required_references:
        assert reference in doctoring
