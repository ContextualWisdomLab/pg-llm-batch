# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for inspected PostgreSQL WAL segment evidence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
    inspect_postgres_backup_artifact,
)
from pg_llm_batch.postgres_wal_segment_evidence import (
    PostgresWalSegmentBinding,
    PostgresWalSegmentEvidenceError,
    bind_postgres_wal_segment_evidence,
    postgres_wal_segment_binding_is_valid,
)

_MIB = 1024 * 1024
_SEGMENT_NAME = "000000010000000000000000"


def _inspected_artifact(
    tmp_path: Path,
    *,
    size_bytes: int = _MIB,
) -> PostgresBackupArtifactEvidence:
    """Return provenance-bearing evidence for one realistic regular WAL-sized file."""
    artifact_path = tmp_path / f"wal-{size_bytes}"
    artifact_path.write_bytes(b"W" * size_bytes)
    return inspect_postgres_backup_artifact(
        str(artifact_path),
        maximum_size_bytes=size_bytes,
    )


def test_binding_requires_real_inspected_bytes_and_reports_nonguarantees(
    tmp_path: Path,
) -> None:
    """A canonical exact-size WAL segment can be bound to inspected byte evidence."""
    artifact = _inspected_artifact(tmp_path)

    binding = bind_postgres_wal_segment_evidence(
        segment_name=_SEGMENT_NAME,
        wal_segment_size_bytes=_MIB,
        artifact_evidence=artifact,
    )

    assert binding.as_dict() == {
        "schema_version": 1,
        "segment_name": _SEGMENT_NAME,
        "wal_segment_size_bytes": _MIB,
        "sha256": artifact.sha256,
        "size_bytes": _MIB,
        "archive_bytes_hashed": True,
        "wal_header_identity_verified": False,
        "timeline_ancestry_verified": False,
        "replay_verified": False,
    }
    assert postgres_wal_segment_binding_is_valid(binding) is True


@pytest.mark.parametrize(
    "segment_name",
    [
        "000000000000000000000000",
        "00000001000000000000000a",
        "00000001000000000000000",
        "000000010000000000000000.partial",
    ],
)
def test_noncanonical_or_zero_timeline_segment_names_fail_closed(
    tmp_path: Path,
    segment_name: str,
) -> None:
    """Only complete canonical uppercase WAL names on a nonzero timeline bind."""
    artifact = _inspected_artifact(tmp_path)
    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^invalid PostgreSQL WAL segment identity$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=segment_name,
            wal_segment_size_bytes=_MIB,
            artifact_evidence=artifact,
        )


def test_hostile_segment_name_subclass_is_rejected_without_rendering(
    tmp_path: Path,
) -> None:
    """Caller-defined string behavior cannot run while validating segment identity."""

    class HostileString(str):
        def __str__(self) -> str:
            raise AssertionError("must not render hostile WAL identity")

    artifact = _inspected_artifact(tmp_path)
    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^invalid PostgreSQL WAL segment identity$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=HostileString(_SEGMENT_NAME),
            wal_segment_size_bytes=_MIB,
            artifact_evidence=artifact,
        )


@pytest.mark.parametrize(
    "wal_segment_size_bytes",
    [True, 0, 3 * _MIB, _MIB + 1, 2048 * _MIB],
)
def test_invalid_wal_segment_sizes_fail_before_artifact_authority(
    tmp_path: Path,
    wal_segment_size_bytes: object,
) -> None:
    """Only PostgreSQL's finite power-of-two MiB segment sizes are accepted."""
    artifact = _inspected_artifact(tmp_path)
    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^invalid PostgreSQL WAL segment size$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=_SEGMENT_NAME,
            wal_segment_size_bytes=wal_segment_size_bytes,  # type: ignore[arg-type]
            artifact_evidence=artifact,
        )


def test_publicly_constructed_backup_evidence_is_not_inspection_proof() -> None:
    """Matching digest/size fields cannot fabricate the protected inspection seam."""
    fabricated = PostgresBackupArtifactEvidence(
        sha256="0" * 64,
        size_bytes=_MIB,
    )
    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^PostgreSQL WAL segment artifact evidence was not inspected$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=_SEGMENT_NAME,
            wal_segment_size_bytes=_MIB,
            artifact_evidence=fabricated,
        )


def test_segment_size_must_match_inspected_artifact_exactly(tmp_path: Path) -> None:
    """A complete archived WAL segment cannot be shorter than its reviewed size."""
    artifact = _inspected_artifact(tmp_path)
    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^PostgreSQL WAL segment artifact size does not match configured segment size$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=_SEGMENT_NAME,
            wal_segment_size_bytes=2 * _MIB,
            artifact_evidence=artifact,
        )


def test_binding_validator_rejects_wrong_type_and_replaced_fields(
    tmp_path: Path,
) -> None:
    """Downstream composition revalidates every security-relevant scalar field."""
    artifact = _inspected_artifact(tmp_path)
    binding = bind_postgres_wal_segment_evidence(
        segment_name=_SEGMENT_NAME,
        wal_segment_size_bytes=_MIB,
        artifact_evidence=artifact,
    )

    assert postgres_wal_segment_binding_is_valid(object()) is False
    assert postgres_wal_segment_binding_is_valid(
        replace(binding, segment_name="000000000000000000000000")
    ) is False
    assert postgres_wal_segment_binding_is_valid(
        replace(binding, wal_segment_size_bytes=3 * _MIB)
    ) is False
    assert postgres_wal_segment_binding_is_valid(
        replace(binding, sha256=b"not-a-string")  # type: ignore[arg-type]
    ) is False
    assert postgres_wal_segment_binding_is_valid(
        replace(binding, size_bytes=True)
    ) is False
    assert postgres_wal_segment_binding_is_valid(
        replace(binding, size_bytes=_MIB - 1)
    ) is False
    assert postgres_wal_segment_binding_is_valid(
        replace(binding, sha256="F" * 64)
    ) is False


def test_binding_validator_rejects_artifact_size_disagreement(tmp_path: Path) -> None:
    """Copied scalar fields cannot disagree with still-valid inspected byte evidence."""
    artifact = _inspected_artifact(tmp_path, size_bytes=2 * _MIB)
    binding = PostgresWalSegmentBinding(
        segment_name=_SEGMENT_NAME,
        wal_segment_size_bytes=_MIB,
        sha256=artifact.sha256,
        size_bytes=_MIB,
        artifact_evidence=artifact,
    )

    assert postgres_wal_segment_binding_is_valid(binding) is False


def test_binding_validator_rejects_lost_underlying_inspection_provenance(
    tmp_path: Path,
) -> None:
    """Mutating the protected artifact snapshot invalidates dependent WAL evidence."""
    artifact = _inspected_artifact(tmp_path)
    binding = bind_postgres_wal_segment_evidence(
        segment_name=_SEGMENT_NAME,
        wal_segment_size_bytes=_MIB,
        artifact_evidence=artifact,
    )

    object.__setattr__(artifact, "size_bytes", _MIB - 1)
    assert postgres_wal_segment_binding_is_valid(binding) is False


def test_direct_binding_construction_without_inspected_artifact_is_invalid() -> None:
    """The public data shape alone never becomes inspected archive-byte evidence."""
    fabricated_artifact = PostgresBackupArtifactEvidence(
        sha256="0" * 64,
        size_bytes=_MIB,
    )
    binding = PostgresWalSegmentBinding(
        segment_name=_SEGMENT_NAME,
        wal_segment_size_bytes=_MIB,
        sha256="0" * 64,
        size_bytes=_MIB,
        artifact_evidence=fabricated_artifact,
    )

    assert postgres_wal_segment_binding_is_valid(binding) is False
