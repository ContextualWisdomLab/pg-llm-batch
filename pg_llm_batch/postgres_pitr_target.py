# SPDX-License-Identifier: Apache-2.0
"""Bind deterministic PostgreSQL PITR recovery targets without starting recovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .postgres_physical_recovery import PostgresPhysicalRecoveryProfile


_LSN_RE = re.compile(r"[0-9A-Fa-f]{1,8}/[0-9A-Fa-f]{1,8}\Z")
_XID_RE = re.compile(r"[1-9][0-9]{0,9}\Z")
_TIME_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?[+-][0-9]{2}:[0-9]{2}\Z"
)
_POINT_IN_TIME_KINDS = frozenset({"time", "xid", "lsn"})
_VALUE_KINDS = _POINT_IN_TIME_KINDS | frozenset({"name"})
_TIMELINE_NAMES = frozenset({"latest", "current"})
_MAX_TIMELINE_ID = (1 << 32) - 1
_MAX_XID = (1 << 32) - 1
_MAX_NAME_BYTES = 256
_MAX_TIME_BYTES = 64


class PostgresPitrTargetError(ValueError):
    """Report a fail-closed PostgreSQL PITR recovery-target violation."""


def _normalize_timeline(timeline: object) -> str:
    """Return one reviewed PostgreSQL recovery timeline representation."""
    if type(timeline) is str and timeline in _TIMELINE_NAMES:
        return timeline
    if type(timeline) is int and 1 <= timeline <= _MAX_TIMELINE_ID:
        return str(timeline)
    raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery timeline")


def _normalize_time(value: object) -> str:
    """Return an exact timezone-aware target time normalized to UTC."""
    if type(value) is not str:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    try:
        encoded_size = len(value.encode("ascii"))
    except UnicodeError:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target") from None
    if not (1 <= encoded_size <= _MAX_TIME_BYTES) or _TIME_RE.fullmatch(value) is None:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    try:
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
    except (ValueError, OverflowError):
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target") from None
    if offset is None:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _normalize_xid(value: object) -> str:
    """Return one canonical normal PostgreSQL 32-bit transaction identifier."""
    if type(value) is not str or _XID_RE.fullmatch(value) is None:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    parsed = int(value, 10)
    if not 3 <= parsed <= _MAX_XID:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    return str(parsed)


def _normalize_lsn(value: object) -> str:
    """Return one canonical nonzero PostgreSQL LSN target."""
    if type(value) is not str or _LSN_RE.fullmatch(value) is None:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    upper = value.upper()
    high, low = upper.split("/", 1)
    if int(high, 16) == 0 and int(low, 16) == 0:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    return f"{int(high, 16):X}/{int(low, 16):X}"


def _normalize_name(value: object) -> str:
    """Return one bounded restore-point name without control characters."""
    if type(value) is not str:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    try:
        encoded_size = len(value.encode("utf-8"))
    except UnicodeError:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target") from None
    if not 1 <= encoded_size <= _MAX_NAME_BYTES:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    return value


def _normalize_target_value(kind: str, value: object) -> str | None:
    """Normalize the value associated with one reviewed recovery-target kind."""
    if kind == "immediate":
        if value is not None:
            raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
        return None
    if kind == "time":
        return _normalize_time(value)
    if kind == "xid":
        return _normalize_xid(value)
    if kind == "lsn":
        return _normalize_lsn(value)
    if kind == "name":
        return _normalize_name(value)
    raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")


def _normalize_inclusive(kind: str, inclusive: object) -> bool | None:
    """Require an explicit inclusion edge only where PostgreSQL supports one."""
    if kind in _POINT_IN_TIME_KINDS:
        if type(inclusive) is not bool:
            raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
        return inclusive
    if inclusive is not None:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")
    return None


def _canonical_target_is_valid(
    *, target_kind: object, target_value: object, inclusive: object, timeline: object
) -> bool:
    """Return whether a constructed target already satisfies canonical form."""
    if type(target_kind) is not str or type(timeline) is not str:
        return False
    if timeline not in _TIMELINE_NAMES:
        if not timeline.isdecimal() or timeline.startswith("0"):
            return False
        timeline_id = int(timeline, 10)
        if not 1 <= timeline_id <= _MAX_TIMELINE_ID:
            return False
    try:
        normalized_value = _normalize_target_value(target_kind, target_value)
        normalized_inclusive = _normalize_inclusive(target_kind, inclusive)
    except PostgresPitrTargetError:
        return False
    return normalized_value == target_value and normalized_inclusive is inclusive


@dataclass(frozen=True, slots=True)
class PostgresPitrRecoveryTarget:
    """Represent one deterministic PostgreSQL PITR stop point for isolated review.

    The object contains server-setting values only. It deliberately omits
    ``restore_command``, filesystem paths, credentials, process execution, and any
    RPO/RTO capability claim. ``recovery_target_action`` is fixed to ``pause`` so a
    target is inspected before a separate operator-controlled promotion decision.
    """

    target_kind: str
    target_value: str | None
    inclusive: bool | None
    timeline: str
    recovery_target_action: str = "pause"

    def __post_init__(self) -> None:
        """Reject direct construction that bypasses the canonical binding contract."""
        if self.recovery_target_action != "pause" or not _canonical_target_is_valid(
            target_kind=self.target_kind,
            target_value=self.target_value,
            inclusive=self.inclusive,
            timeline=self.timeline,
        ):
            raise PostgresPitrTargetError("invalid PostgreSQL PITR recovery target")

    def server_settings(self) -> tuple[tuple[str, str], ...]:
        """Return deterministic PostgreSQL recovery settings without a restore command."""
        if self.target_kind == "immediate":
            target_setting = ("recovery_target", "immediate")
        else:
            target_setting = (f"recovery_target_{self.target_kind}", self.target_value)
        settings: list[tuple[str, str]] = [target_setting]  # type: ignore[list-item]
        if self.inclusive is not None:
            settings.append(("recovery_target_inclusive", "on" if self.inclusive else "off"))
        settings.extend(
            (
                ("recovery_target_timeline", self.timeline),
                ("recovery_target_action", "pause"),
            )
        )
        return tuple(settings)


def bind_postgres_pitr_recovery_target(
    profile: PostgresPhysicalRecoveryProfile,
    *,
    target_value: str | None,
    inclusive: bool | None,
    timeline: str | int,
) -> PostgresPitrRecoveryTarget:
    """Bind one deterministic PITR stop point without configuring or starting PostgreSQL.

    ``profile`` must be the exact reviewed physical-recovery profile type and must
    select ``backup_method="pitr"`` with a WAL archive. The profile's target kind is
    authoritative; callers cannot silently switch it at execution time. Time targets
    require an explicit numeric UTC offset and are normalized to UTC. XID and LSN
    targets are canonicalized, named restore points are bounded and reject control
    characters, and ``immediate`` carries no value. ``recovery_target_inclusive`` is
    mandatory for time/XID/LSN and forbidden for name/immediate. Timelines are limited
    to PostgreSQL's reviewed ``latest``/``current`` names or an exact positive uint32
    timeline identifier.

    The returned settings always pause at the target for isolated acceptance. This
    seam does not provide ``restore_command``, create ``recovery.signal``, execute WAL
    replay, verify archive continuity, promote a cluster, or establish RPO/RTO.
    """
    if type(profile) is not PostgresPhysicalRecoveryProfile:
        raise PostgresPitrTargetError("invalid PostgreSQL PITR profile")
    if profile.backup_method != "pitr" or profile.wal_archive_required is not True:
        raise PostgresPitrTargetError(
            "PostgreSQL PITR target requires a PITR profile with WAL archive"
        )
    normalized_timeline = _normalize_timeline(timeline)
    normalized_value = _normalize_target_value(profile.recovery_target_kind, target_value)
    normalized_inclusive = _normalize_inclusive(profile.recovery_target_kind, inclusive)
    return PostgresPitrRecoveryTarget(
        target_kind=profile.recovery_target_kind,
        target_value=normalized_value,
        inclusive=normalized_inclusive,
        timeline=normalized_timeline,
    )
