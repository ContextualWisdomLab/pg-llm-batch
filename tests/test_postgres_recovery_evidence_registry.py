# SPDX-License-Identifier: Apache-2.0
"""Regression tests for stale PostgreSQL recovery-evidence registry callbacks."""

from __future__ import annotations

import gc
from pathlib import Path
from weakref import ref

import pg_llm_batch.postgres_backup_evidence as backup_evidence
import pg_llm_batch.postgres_schema_evidence as schema_evidence


def test_backup_registry_stale_callback_preserves_replacement_entry(
    tmp_path: Path,
) -> None:
    """A stale backup weakref callback must not delete a replacement registry slot."""
    artifact = tmp_path / "tenant-backup.dump"
    artifact.write_bytes(b"bounded-backup-evidence")
    evidence = backup_evidence.inspect_postgres_backup_artifact(str(artifact))
    evidence_id = id(evidence)
    stale_reference = backup_evidence._INSPECTED_BACKUP_EVIDENCE_IDS[evidence_id][0]
    replacement = backup_evidence.PostgresBackupArtifactEvidence("0" * 64, 1)
    replacement_entry = (ref(replacement), replacement.sha256, replacement.size_bytes)
    backup_evidence._INSPECTED_BACKUP_EVIDENCE_IDS[evidence_id] = replacement_entry

    try:
        del evidence
        gc.collect()
        assert stale_reference() is None
        assert backup_evidence._INSPECTED_BACKUP_EVIDENCE_IDS[evidence_id] == replacement_entry
    finally:
        backup_evidence._INSPECTED_BACKUP_EVIDENCE_IDS.pop(evidence_id, None)


def test_schema_registry_stale_callback_preserves_replacement_entry() -> None:
    """A stale schema weakref callback must not delete a replacement registry slot."""
    evidence = schema_evidence.inspect_postgres_schema()
    evidence_id = id(evidence)
    stale_reference = schema_evidence._INSPECTED_SCHEMA_EVIDENCE_IDS[evidence_id][0]
    replacement = schema_evidence.PostgresSchemaEvidence("0" * 64, 1)
    replacement_entry = (ref(replacement), replacement.sha256, replacement.size_bytes)
    schema_evidence._INSPECTED_SCHEMA_EVIDENCE_IDS[evidence_id] = replacement_entry

    try:
        del evidence
        gc.collect()
        assert stale_reference() is None
        assert schema_evidence._INSPECTED_SCHEMA_EVIDENCE_IDS[evidence_id] == replacement_entry
    finally:
        schema_evidence._INSPECTED_SCHEMA_EVIDENCE_IDS.pop(evidence_id, None)
