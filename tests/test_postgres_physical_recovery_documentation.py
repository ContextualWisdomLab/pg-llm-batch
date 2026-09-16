# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for bounded physical/WAL/PITR recovery profiles."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/postgres-physical-pitr-profile.md")
ADR = Path("docs/adr/0019-postgres-physical-pitr-profile.md")


def _normalized(path: Path) -> str:
    """Read one authoritative document with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_physical_pitr_docs_record_operator_and_citation_contract() -> None:
    """Operators must see isolation, WAL, time-flow, and non-capability steps."""
    documents = (_normalized(DOCTORING), _normalized(ADR))
    for document in documents:
        assert "isolated_target_prepared" in document
        assert "wal_archive_required" in document
        assert "package_capability_claim" in document
        assert "point-in-time" in document or "point in time" in document
        assert "pg_basebackup" in document
        assert "backup-internal wal" in document or "backup-internal" in document
        assert "continuous" in document and "archive" in document
        assert "immediate" in document
        assert "end-of-backup" in document
        assert "replay-to-end-of-archive" in document
        assert "swanson" in document
        assert "nist" in document
        assert "postgresql" in document
        assert "continuous archiving" in document


def test_physical_pitr_docs_bind_recovery_target_observer_handoff() -> None:
    """ADR and operator docs must preserve the bounded #299 observation seam."""
    setting_names = (
        "recovery_target",
        "recovery_target_action",
        "recovery_target_inclusive",
        "recovery_target_lsn",
        "recovery_target_name",
        "recovery_target_time",
        "recovery_target_timeline",
        "recovery_target_xid",
    )
    documents = (_normalized(DOCTORING), _normalized(ADR))
    for document in documents:
        assert "observe_postgres_recovery_target_configuration" in document
        for setting_name in setting_names:
            assert setting_name in document
        assert "pg_is_in_recovery()" in document
        assert "read-only" in document
        assert "bounded" in document
        assert "fail" in document and "closed" in document
        assert "pending_restart" in document
        assert "content-free" in document
        assert "recovery.signal" in document
        assert "restore_command" in document
        assert "target" in document and (
            "attainment" in document or "target was reached" in document
        )
        assert "promote" in document
        assert "application readiness" in document
