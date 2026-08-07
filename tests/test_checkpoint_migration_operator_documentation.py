# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for the atomic checkpoint migration operator."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    """Read one authoritative repository document as UTF-8 text."""
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_operator_documentation_is_complete_and_body_free() -> None:
    """README and operator guide explain the safe opt-in workflow to beginners."""
    combined = "\n".join(
        (
            _read("README.md"),
            _read("docs/checkpoint-storage-migrations.md"),
        )
    )
    required = (
        "init-checkpoint-storage",
        "0007_result_stream_checkpoints",
        "0008_result_checkpoint_audit_events",
        "before database access",
        "pg_advisory_xact_lock",
        "one transaction",
        "one commit",
        "rolls back",
        "1 MiB",
        "not a signature",
        "init-db",
        "existing PostgreSQL volumes",
    )
    for phrase in required:
        assert phrase in combined
    forbidden = (
        "prints the DSN",
        "prints SQL text",
        "migration ledger table",
        "downgrade retained evidence",
    )
    for phrase in forbidden:
        assert phrase not in combined


def test_contributor_invariants_define_atomic_migration_ownership() -> None:
    """Agent contracts preserve ordering, locking, compatibility, and evidence."""
    for path in ("AGENTS.md", "CLAUDE.md"):
        content = _read(path)
        required = (
            "Checkpoint migration operator",
            "init-checkpoint-storage",
            "0007_result_stream_checkpoints",
            "0008_result_checkpoint_audit_events",
            "transaction-level advisory lock",
            "before database access",
            "one commit",
            "not a signature",
            "100% production statement, branch, and public-docstring coverage",
        )
        for phrase in required:
            assert phrase in content


def test_architecture_adr_changelog_and_doctoring_are_synchronized() -> None:
    """Authoritative design and assurance records describe one shared boundary."""
    documents = (
        _read("ARCHITECTURE.md"),
        _read("CHANGELOG.md"),
        _read("docs/adr/0010-atomic-checkpoint-schema-operator.md"),
        _read("docs/doctoring/checkpoint-migration-operator.md"),
    )
    for content in documents:
        required = (
            "init-checkpoint-storage",
            "0007_result_stream_checkpoints",
            "0008_result_checkpoint_audit_events",
            "pg_advisory_xact_lock",
            "SHA-256",
        )
        for phrase in required:
            assert phrase in content

    doctoring = documents[-1]
    assert "NIST Special Publication 800-53, Revision 5" in doctoring
    assert "PostgreSQL Global Development Group. (2026)." in doctoring
    assert "CM-3" in doctoring
    assert "transaction-level" in doctoring
    assert "administrator" in doctoring
