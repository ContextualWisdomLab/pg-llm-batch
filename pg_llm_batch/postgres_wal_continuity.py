# SPDX-License-Identifier: Apache-2.0
"""Assess bounded single-timeline PostgreSQL WAL filename continuity."""

from __future__ import annotations

import re
from dataclasses import dataclass

_MIB = 1024 * 1024
_MIN_WAL_SEGMENT_SIZE_BYTES = 1 * _MIB
_MAX_WAL_SEGMENT_SIZE_BYTES = 1024 * _MIB
_MAX_TIMELINE_ID = (1 << 32) - 1
_MAX_WAL_SEGMENTS = 4096
_LSN_PATTERN = re.compile(r"[0-9A-F]{1,8}/[0-9A-F]{1,8}\Z", re.ASCII)
_SEGMENT_NAME_PATTERN = re.compile(r"[0-9A-F]{24}\Z", re.ASCII)


class PostgresWalContinuityError(ValueError):
    """Report a fail-closed bounded WAL manifest continuity violation."""


def _parse_lsn(value: object) -> int | None:
    """Return the 64-bit value of one canonical PostgreSQL LSN, else ``None``."""
    if type(value) is not str:
        return None
    if _LSN_PATTERN.fullmatch(value) is None:
        return None
    high_text, low_text = value.split("/", 1)
    return (int(high_text, 16) << 32) | int(low_text, 16)


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


def _canonical_segment_name(
    *, timeline_id: int, segment_number: int, wal_segment_size_bytes: int
) -> str:
    """Return PostgreSQL's canonical 24-hex name for one WAL segment number."""
    segments_per_log_id = (1 << 32) // wal_segment_size_bytes
    log_id = segment_number // segments_per_log_id
    segment_id = segment_number % segments_per_log_id
    return f"{timeline_id:08X}{log_id:08X}{segment_id:08X}"


@dataclass(frozen=True, slots=True)
class PostgresWalContinuityAssessment:
    """Describe exact filename coverage for one bounded single-timeline WAL span.

    The assessment proves only that the caller supplied the canonical ordered
    segment names required to cover ``start_lsn`` through the segment containing
    ``target_lsn`` for one explicit timeline and WAL segment size. It does not
    inspect archive bytes, prove cluster identity or timeline ancestry, execute
    replay, or establish PITR, RPO, or RTO.
    """

    timeline_id: int
    wal_segment_size_bytes: int
    start_lsn: str
    target_lsn: str
    first_segment_name: str
    last_segment_name: str
    segment_count: int

    @property
    def archive_bytes_verified(self) -> bool:
        """Return ``False`` because filename continuity does not inspect WAL bytes."""
        return False

    @property
    def timeline_ancestry_verified(self) -> bool:
        """Return ``False`` because one timeline identifier is not ancestry proof."""
        return False

    @property
    def replay_verified(self) -> bool:
        """Return ``False`` because manifest assessment never executes WAL replay."""
        return False

    def as_dict(self) -> dict[str, object]:
        """Return stable content-free machine-readable continuity metadata."""
        return {
            "schema_version": 1,
            "timeline_id": self.timeline_id,
            "wal_segment_size_bytes": self.wal_segment_size_bytes,
            "start_lsn": self.start_lsn,
            "target_lsn": self.target_lsn,
            "first_segment_name": self.first_segment_name,
            "last_segment_name": self.last_segment_name,
            "segment_count": self.segment_count,
            "archive_bytes_verified": self.archive_bytes_verified,
            "timeline_ancestry_verified": self.timeline_ancestry_verified,
            "replay_verified": self.replay_verified,
        }


def assess_postgres_wal_continuity(
    *,
    wal_segment_size_bytes: int,
    timeline_id: int,
    start_lsn: str,
    target_lsn: str,
    segment_names: tuple[str, ...],
) -> PostgresWalContinuityAssessment:
    """Assess exact canonical WAL filename coverage through an inclusive target LSN.

    ``start_lsn`` and ``target_lsn`` are canonical uppercase PostgreSQL LSN text.
    ``segment_names`` must be an exact tuple of complete canonical 24-hex WAL
    filenames in replay order. PostgreSQL permits power-of-two WAL segment sizes
    from 1 MiB through 1 GiB; the caller must provide the source cluster's exact
    size. PostgreSQL deliberately does not use the first segment containing LSN
    ``0/0``, so a continuity interval may not start there. At most 4096 segments
    are assessed in one call.

    This seam deliberately does not read files, infer timeline history, validate
    WAL record bytes, contact PostgreSQL, or run restore/replay commands.
    """
    if not _valid_wal_segment_size(wal_segment_size_bytes):
        raise PostgresWalContinuityError(
            "invalid PostgreSQL WAL continuity request"
        )
    if type(timeline_id) is not int or not 1 <= timeline_id <= _MAX_TIMELINE_ID:
        raise PostgresWalContinuityError(
            "invalid PostgreSQL WAL continuity request"
        )
    start_value = _parse_lsn(start_lsn)
    target_value = _parse_lsn(target_lsn)
    if start_value is None or target_value is None:
        raise PostgresWalContinuityError(
            "invalid PostgreSQL WAL continuity request"
        )
    if type(segment_names) is not tuple:
        raise PostgresWalContinuityError(
            "invalid PostgreSQL WAL continuity request"
        )
    if len(segment_names) > _MAX_WAL_SEGMENTS:
        raise PostgresWalContinuityError(
            "PostgreSQL WAL continuity span exceeds bounded segment budget"
        )
    for segment_name in segment_names:
        if (
            type(segment_name) is not str
            or _SEGMENT_NAME_PATTERN.fullmatch(segment_name) is None
        ):
            raise PostgresWalContinuityError(
                "invalid PostgreSQL WAL segment manifest"
            )
    if target_value < start_value:
        raise PostgresWalContinuityError(
            "PostgreSQL WAL target precedes archive start"
        )

    first_segment_number = start_value // wal_segment_size_bytes
    last_segment_number = target_value // wal_segment_size_bytes
    expected_count = last_segment_number - first_segment_number + 1
    if expected_count > _MAX_WAL_SEGMENTS:
        raise PostgresWalContinuityError(
            "PostgreSQL WAL continuity span exceeds bounded segment budget"
        )
    if first_segment_number == 0:
        raise PostgresWalContinuityError(
            "invalid PostgreSQL WAL continuity request"
        )

    expected_names = tuple(
        _canonical_segment_name(
            timeline_id=timeline_id,
            segment_number=segment_number,
            wal_segment_size_bytes=wal_segment_size_bytes,
        )
        for segment_number in range(first_segment_number, last_segment_number + 1)
    )
    if segment_names != expected_names:
        raise PostgresWalContinuityError(
            "PostgreSQL WAL manifest is not exactly continuous"
        )

    return PostgresWalContinuityAssessment(
        timeline_id=timeline_id,
        wal_segment_size_bytes=wal_segment_size_bytes,
        start_lsn=start_lsn,
        target_lsn=target_lsn,
        first_segment_name=expected_names[0],
        last_segment_name=expected_names[-1],
        segment_count=expected_count,
    )
