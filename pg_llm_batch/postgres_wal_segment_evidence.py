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
    """Return whether ``value`` is one lexical nonzero-timeline WAL filename."""
    return (
        type(value) is str
        and _SEGMENT_NAME_PATTERN.fullmatch(value) is not None
        and value[:8] != "00000000"
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
        """Return stable content-free WAL segment evidence metadata."""
        return {
            "schema_version": 1,
            "segment_name": self.segment_name,
            "wal_segment_size_bytes": self.wal_segment_size_bytes,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "archive_bytes_hashed": self.archive_bytes_hashed,
            "wal_header_identity_verified": self.wal_header_identity_verified,
            "timeline_ancestry_verified": self.timeline_ancestry_verified,
            "replay_verified": self.replay_verified,
        }


def postgres_wal_segment_binding_is_valid(binding: object) -> bool:
    """Return whether every authority-bearing field still matches inspected bytes."""
    if type(binding) is not PostgresWalSegmentBinding:
        return False
    if not _valid_segment_name(binding.segment_name):
        return False
    if not _valid_wal_segment_size(binding.wal_segment_size_bytes):
        return False
    if not _segment_name_matches_size(
        binding.segment_name,
        binding.wal_segment_size_bytes,
    ):
        return False
    if not postgres_backup_artifact_evidence_was_inspected(binding.artifact_evidence):
        return False
    return (
        type(binding.sha256) is str
        and type(binding.size_bytes) is int
        and binding.size_bytes == binding.wal_segment_size_bytes
        and binding.sha256 == binding.artifact_evidence.sha256
        and binding.size_bytes == binding.artifact_evidence.size_bytes
    )


def bind_postgres_wal_segment_evidence(
    *,
    segment_name: str,
    wal_segment_size_bytes: int,
    artifact_evidence: PostgresBackupArtifactEvidence,
) -> PostgresWalSegmentBinding:
    """Bind canonical WAL identity to exact protected stable-file inspection evidence.

    PostgreSQL WAL segment sizes are constrained here to the supported
    power-of-two 1 MiB through 1 GiB range. The filename must also be one that
    PostgreSQL's segment-size-dependent filename geometry can emit.
    ``artifact_evidence`` must be the exact live object returned by the protected
    backup-artifact inspector, and its observed byte count must equal the reviewed
    WAL segment size.

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
