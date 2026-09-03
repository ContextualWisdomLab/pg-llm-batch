# SPDX-License-Identifier: Apache-2.0
"""Bind inspected artifact bytes to one PostgreSQL WAL segment identity."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
    postgres_backup_artifact_evidence_was_inspected,
)

_MIB = 1024 * 1024
_MIN_WAL_SEGMENT_SIZE_BYTES = 1 * _MIB
_MAX_WAL_SEGMENT_SIZE_BYTES = 1024 * _MIB
_SEGMENT_NAME_PATTERN = re.compile(r"[0-9A-F]{24}\Z", re.ASCII)


class PostgresWalSegmentEvidenceError(ValueError):
    """Report a fail-closed PostgreSQL WAL segment evidence violation."""


def _valid_segment_name(value: object) -> bool:
    """Return whether ``value`` is one lexical WAL filename PostgreSQL can use."""
    return (
        type(value) is str
        and _SEGMENT_NAME_PATTERN.fullmatch(value) is not None
        and value[:8] != "00000000"
        and value[8:] != "0000000000000000"
    )


def _valid_wal_segment_size(value: object) -> bool:
    """Return whether ``value`` is a reviewed PostgreSQL WAL segment size."""
    if type(value) is not int:
        return False
    if not _MIN_WAL_SEGMENT_SIZE_BYTES <= value <= _MAX_WAL_SEGMENT_SIZE_BYTES:
        return False
    if value % _MIB != 0:
        return False
    megabytes = value // _MIB
    return megabytes & (megabytes - 1) == 0


def _segment_name_matches_size(segment_name: str, wal_segment_size_bytes: int) -> bool:
    """Return whether PostgreSQL can canonically emit this name at this segment size."""
    segments_per_log_id = (1 << 32) // wal_segment_size_bytes
    segment_id = int(segment_name[16:24], 16)
    return segment_id < segments_per_log_id


@dataclass(frozen=True)
class PostgresWalSegmentBinding:
    """Bind one canonical WAL filename to already-inspected stable file bytes.

    ``artifact_evidence`` remains attached so downstream composition can
    revalidate the protected inspection provenance instead of trusting copied
    digest/size fields. The binding does not parse the WAL header, establish
    timeline ancestry, prove replayability, or execute recovery.
    """

    segment_name: str
    wal_segment_size_bytes: int
    sha256: str
    size_bytes: int
    artifact_evidence: PostgresBackupArtifactEvidence = field(
        repr=False,
        compare=False,
    )

    @property
    def archive_bytes_hashed(self) -> bool:
        """Return ``True`` only for a currently valid inspected-artifact binding."""
        return postgres_wal_segment_binding_is_valid(self)

    @property
    def wal_header_identity_verified(self) -> bool:
        """Return ``False`` because this seam does not parse WAL headers."""
        return False

    @property
    def timeline_ancestry_verified(self) -> bool:
        """Return ``False`` because one filename cannot establish timeline ancestry."""
        return False

    @property
    def replay_verified(self) -> bool:
        """Return ``False`` because byte hashing never executes WAL replay."""
        return False

    def as_dict(self) -> dict[str, object]:
        """Return one validated content-free WAL evidence snapshot.

        Serialization fails closed if caller-accessible dataclass fields no longer
        match the protected inspection evidence. The returned mapping is built
        only from the scalar snapshot that passed validation, so later mutation
        cannot mix unvalidated authority fields into a positive evidence receipt.
        """
        snapshot = _validated_binding_snapshot(self)
        if snapshot is None:
            raise PostgresWalSegmentEvidenceError(
                "PostgreSQL WAL segment binding is invalid"
            )
        segment_name, wal_segment_size_bytes, sha256, size_bytes = snapshot
        return {
            "schema_version": 1,
            "segment_name": segment_name,
            "wal_segment_size_bytes": wal_segment_size_bytes,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "archive_bytes_hashed": True,
            "wal_header_identity_verified": False,
            "timeline_ancestry_verified": False,
            "replay_verified": False,
        }


def _validated_binding_snapshot(
    binding: object,
) -> tuple[str, int, str, int] | None:
    """Return stable authority fields only when one validation window stays unchanged."""
    if type(binding) is not PostgresWalSegmentBinding:
        return None

    segment_name = binding.segment_name
    wal_segment_size_bytes = binding.wal_segment_size_bytes
    sha256 = binding.sha256
    size_bytes = binding.size_bytes
    artifact_evidence = binding.artifact_evidence

    if not _valid_segment_name(segment_name):
        return None
    if not _valid_wal_segment_size(wal_segment_size_bytes):
        return None
    if not _segment_name_matches_size(segment_name, wal_segment_size_bytes):
        return None
    if type(sha256) is not str or type(size_bytes) is not int:
        return None
    if type(artifact_evidence) is not PostgresBackupArtifactEvidence:
        return None

    artifact_sha256 = artifact_evidence.sha256
    artifact_size_bytes = artifact_evidence.size_bytes
    if type(artifact_sha256) is not str or type(artifact_size_bytes) is not int:
        return None
    if (
        size_bytes != wal_segment_size_bytes
        or sha256 != artifact_sha256
        or size_bytes != artifact_size_bytes
    ):
        return None
    if not postgres_backup_artifact_evidence_was_inspected(artifact_evidence):
        return None

    if (
        binding.segment_name != segment_name
        or binding.wal_segment_size_bytes != wal_segment_size_bytes
        or binding.sha256 != sha256
        or binding.size_bytes != size_bytes
        or binding.artifact_evidence is not artifact_evidence
        or artifact_evidence.sha256 != artifact_sha256
        or artifact_evidence.size_bytes != artifact_size_bytes
    ):
        return None

    return segment_name, wal_segment_size_bytes, sha256, size_bytes


def postgres_wal_segment_binding_is_valid(binding: object) -> bool:
    """Return whether every authority-bearing field still matches inspected bytes."""
    return _validated_binding_snapshot(binding) is not None


def bind_postgres_wal_segment_evidence(
    *,
    segment_name: str,
    wal_segment_size_bytes: int,
    artifact_evidence: PostgresBackupArtifactEvidence,
) -> PostgresWalSegmentBinding:
    """Bind canonical WAL identity to exact protected stable-file inspection evidence.

    PostgreSQL WAL segment sizes are constrained here to the supported
    power-of-two 1 MiB through 1 GiB range. The filename must also be one that
    PostgreSQL's segment-size-dependent filename geometry can emit, excluding the
    bootstrap-skipped segment containing invalid LSN zero. ``artifact_evidence``
    must be the exact live object returned by the protected backup-artifact
    inspector, and its observed byte count must equal the reviewed WAL segment size.

    This function intentionally does not inspect a WAL header or record stream,
    infer cluster identity/timeline history, validate archive ordering, or run
    restore/replay commands.
    """
    if not _valid_segment_name(segment_name):
        raise PostgresWalSegmentEvidenceError(
            "invalid PostgreSQL WAL segment identity"
        )
    if not _valid_wal_segment_size(wal_segment_size_bytes):
        raise PostgresWalSegmentEvidenceError(
            "invalid PostgreSQL WAL segment size"
        )
    if not _segment_name_matches_size(segment_name, wal_segment_size_bytes):
        raise PostgresWalSegmentEvidenceError(
            "invalid PostgreSQL WAL segment identity"
        )
    if not postgres_backup_artifact_evidence_was_inspected(artifact_evidence):
        raise PostgresWalSegmentEvidenceError(
            "PostgreSQL WAL segment artifact evidence was not inspected"
        )
    if artifact_evidence.size_bytes != wal_segment_size_bytes:
        raise PostgresWalSegmentEvidenceError(
            "PostgreSQL WAL segment artifact size does not match configured segment size"
        )

    return PostgresWalSegmentBinding(
        segment_name=segment_name,
        wal_segment_size_bytes=wal_segment_size_bytes,
        sha256=artifact_evidence.sha256,
        size_bytes=artifact_evidence.size_bytes,
        artifact_evidence=artifact_evidence,
    )
