# SPDX-License-Identifier: Apache-2.0
"""Assess bounded PostgreSQL timeline-history structure without replay claims."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_MAX_TIMELINE_ID = (1 << 32) - 1
_MAX_HISTORY_BYTES = 64 * 1024
_PARENT_TIMELINE_PATTERN = re.compile(rb"[0-9]{1,10}\Z", re.ASCII)
_LSN_PATTERN = re.compile(
    rb"([0-9A-Fa-f]{1,8})/([0-9A-Fa-f]{1,8})\Z",
    re.ASCII,
)


class PostgresTimelineHistoryError(ValueError):
    """Report a fail-closed PostgreSQL timeline-history evidence violation."""


def _parse_parent_timeline(value: bytes) -> int | None:
    """Return one valid nonzero PostgreSQL timeline ID, else ``None``."""
    if _PARENT_TIMELINE_PATTERN.fullmatch(value) is None:
        return None
    parsed = int(value, 10)
    if not 1 <= parsed <= _MAX_TIMELINE_ID:
        return None
    return parsed


def _parse_switchpoint(value: bytes) -> tuple[int, str] | None:
    """Return one bounded LSN value plus stable canonical PostgreSQL LSN text."""
    matched = _LSN_PATTERN.fullmatch(value)
    if matched is None:
        return None
    high = int(matched.group(1), 16)
    low = int(matched.group(2), 16)
    numeric = (high << 32) | low
    return numeric, f"{high:X}/{low:08X}"


@dataclass(frozen=True, slots=True)
class PostgresTimelineHistoryAssessment:
    """Describe bounded structural evidence from caller-supplied history bytes.

    The assessment proves only that the supplied bytes satisfy this package's
    PostgreSQL-compatible ancestry and switchpoint structure checks for the
    explicit target timeline. Human-readable reason text is intentionally not
    retained. Archive provenance, WAL-byte identity, replay, and recovery remain
    separate evidence domains.
    """

    target_timeline_id: int
    ancestor_timeline_ids: tuple[int, ...]
    switchpoints: tuple[str, ...]
    history_content_sha256: str

    @property
    def history_structure_verified(self) -> bool:
        """Return ``True`` because construction follows successful structure checks."""
        return True

    @property
    def archive_provenance_verified(self) -> bool:
        """Return ``False`` because caller-supplied bytes have no archive authority."""
        return False

    @property
    def replay_verified(self) -> bool:
        """Return ``False`` because parsing history never executes WAL replay."""
        return False

    def as_dict(self) -> dict[str, object]:
        """Return stable content-free timeline-history evidence metadata."""
        return {
            "schema_version": 1,
            "target_timeline_id": self.target_timeline_id,
            "ancestor_timeline_ids": self.ancestor_timeline_ids,
            "switchpoints": self.switchpoints,
            "history_content_sha256": self.history_content_sha256,
            "history_structure_verified": self.history_structure_verified,
            "archive_provenance_verified": self.archive_provenance_verified,
            "replay_verified": self.replay_verified,
        }


def assess_postgres_timeline_history(
    *,
    target_timeline_id: int,
    history_content: bytes,
) -> PostgresTimelineHistoryAssessment:
    """Assess bounded PostgreSQL timeline-history bytes for one child timeline.

    PostgreSQL history files contain parent timeline IDs, switchpoint LSNs, and
    human-readable reasons. Comments and blank lines are ignored. This parser
    consumes raw bytes so reason text never needs to be decoded or exported,
    validates parent IDs in increasing order below the explicit child timeline,
    and requires switchpoints to be nondecreasing along that ancestry.

    At most 64 KiB of caller-supplied history is accepted. The returned SHA-256
    binds the assessment to those exact bytes but does not prove where they came
    from. The function does not inspect WAL segments, prove cluster identity,
    execute replay, or establish PITR/RPO/RTO.
    """
    if type(target_timeline_id) is not int or not (
        1 <= target_timeline_id <= _MAX_TIMELINE_ID
    ):
        raise PostgresTimelineHistoryError(
            "invalid PostgreSQL timeline history request"
        )
    if type(history_content) is not bytes or len(history_content) > _MAX_HISTORY_BYTES:
        raise PostgresTimelineHistoryError(
            "invalid PostgreSQL timeline history request"
        )

    parent_timeline_ids: list[int] = []
    switchpoint_texts: list[str] = []
    previous_parent_timeline: int | None = None
    previous_switchpoint: int | None = None

    for line in history_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(b"#"):
            continue
        fields = stripped.split(maxsplit=2)
        if len(fields) < 2:
            raise PostgresTimelineHistoryError(
                "invalid PostgreSQL timeline history entry"
            )

        parent_timeline = _parse_parent_timeline(fields[0])
        parsed_switchpoint = _parse_switchpoint(fields[1])
        if parent_timeline is None or parsed_switchpoint is None:
            raise PostgresTimelineHistoryError(
                "invalid PostgreSQL timeline history entry"
            )
        switchpoint, switchpoint_text = parsed_switchpoint

        if parent_timeline >= target_timeline_id:
            raise PostgresTimelineHistoryError(
                "invalid PostgreSQL timeline history ancestry"
            )
        if (
            previous_parent_timeline is not None
            and parent_timeline <= previous_parent_timeline
        ):
            raise PostgresTimelineHistoryError(
                "invalid PostgreSQL timeline history ancestry"
            )
        if previous_switchpoint is not None and switchpoint < previous_switchpoint:
            raise PostgresTimelineHistoryError(
                "invalid PostgreSQL timeline history switchpoint order"
            )

        parent_timeline_ids.append(parent_timeline)
        switchpoint_texts.append(switchpoint_text)
        previous_parent_timeline = parent_timeline
        previous_switchpoint = switchpoint

    if target_timeline_id > 1 and not parent_timeline_ids:
        raise PostgresTimelineHistoryError(
            "invalid PostgreSQL timeline history ancestry"
        )

    return PostgresTimelineHistoryAssessment(
        target_timeline_id=target_timeline_id,
        ancestor_timeline_ids=tuple(parent_timeline_ids),
        switchpoints=tuple(switchpoint_texts),
        history_content_sha256=hashlib.sha256(history_content).hexdigest(),
    )
