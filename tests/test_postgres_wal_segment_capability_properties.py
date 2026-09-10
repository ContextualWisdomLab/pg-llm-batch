# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for PostgreSQL WAL evidence capability properties."""

from pathlib import Path

from pg_llm_batch.postgres_backup_evidence import inspect_postgres_backup_artifact
from pg_llm_batch.postgres_wal_segment_evidence import bind_postgres_wal_segment_evidence

_MIB = 1024 * 1024
_SEGMENT_NAME = "000000010000000000000001"


def test_binding_capability_properties_report_only_proven_authority(
    tmp_path: Path,
) -> None:
    """Capability properties expose byte proof while preserving explicit non-guarantees."""
    artifact_path = tmp_path / "wal-segment"
    artifact_path.write_bytes(b"W" * _MIB)
    artifact = inspect_postgres_backup_artifact(
        str(artifact_path),
        maximum_size_bytes=_MIB,
    )
    binding = bind_postgres_wal_segment_evidence(
        segment_name=_SEGMENT_NAME,
        wal_segment_size_bytes=_MIB,
        artifact_evidence=artifact,
    )

    assert binding.archive_bytes_hashed is True
    assert binding.wal_header_identity_verified is False
    assert binding.timeline_ancestry_verified is False
    assert binding.replay_verified is False
