# SPDX-License-Identifier: Apache-2.0
"""Bind a caller-owned physical/WAL/PITR recovery profile without executing backup."""

from __future__ import annotations

import json
from dataclasses import dataclass


_BACKUP_METHODS = frozenset({"physical", "pitr"})
_POINT_IN_TIME_KINDS = frozenset({"time", "xid", "name", "lsn"})
_RECOVERY_TARGET_KINDS = frozenset({"immediate"}) | _POINT_IN_TIME_KINDS
_PROFILE_KEYS = frozenset(
    {
        "schema_version",
        "postgres_major",
        "backup_method",
        "recovery_target_kind",
        "wal_archive_required",
        "isolated_target_prepared",
        "rpo_seconds",
        "rto_seconds",
        "package_capability_claim",
    }
)
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_MAX_PROFILE_JSON_BYTES = 2048


class PostgresPhysicalRecoveryError(ValueError):
    """Report a fail-closed physical/WAL/PITR recovery-profile violation."""


def _exact_major(value: object) -> bool:
    """Return whether a value is an exact PostgreSQL major-version integer."""
    return type(value) is int and 1 <= value <= 99


def _exact_method(value: object) -> bool:
    """Return whether a value is one reviewed physical or PITR method string."""
    return type(value) is str and value in _BACKUP_METHODS


def _exact_target_kind(value: object) -> bool:
    """Return whether a value is one reviewed recovery-target kind string."""
    return type(value) is str and value in _RECOVERY_TARGET_KINDS


def _exact_bool(value: object) -> bool:
    """Return whether a value is an exact built-in boolean."""
    return type(value) is bool


def _optional_positive_seconds(value: object) -> bool:
    """Return whether a value is omitted or an exact positive second budget."""
    return value is None or (
        type(value) is int and 1 <= value <= _MAX_SIGNED_BIGINT
    )


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Build one JSON object while rejecting ambiguous duplicate member names."""
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            raise PostgresPhysicalRecoveryError(
                "invalid PostgreSQL physical recovery profile schema"
            )
        decoded[key] = value
    return decoded


@dataclass(frozen=True, slots=True)
class PostgresPhysicalRecoveryProfile:
    """Represent one caller-owned physical or PITR recovery profile.

    The profile records deployer-selected method, time-flow target kind, WAL
    archive necessity, isolated-target readiness, and optional RPO/RTO
    objectives. It does not execute ``pg_basebackup``, archive WAL, or restore
    a cluster, and it never claims those objectives as package capability.
    """

    postgres_major: int
    backup_method: str
    recovery_target_kind: str
    wal_archive_required: bool
    isolated_target_prepared: bool
    rpo_seconds: int | None
    rto_seconds: int | None

    def __post_init__(self) -> None:
        """Fail closed when the profile violates the bounded recovery contract."""
        if not (
            _exact_major(self.postgres_major)
            and _exact_method(self.backup_method)
            and _exact_target_kind(self.recovery_target_kind)
            and _exact_bool(self.wal_archive_required)
            and _exact_bool(self.isolated_target_prepared)
            and _optional_positive_seconds(self.rpo_seconds)
            and _optional_positive_seconds(self.rto_seconds)
        ):
            raise PostgresPhysicalRecoveryError(
                "invalid PostgreSQL physical recovery profile"
            )
        if self.isolated_target_prepared is False:
            raise PostgresPhysicalRecoveryError(
                "PostgreSQL physical recovery requires an isolated target"
            )
        if self.backup_method == "pitr" and self.wal_archive_required is False:
            raise PostgresPhysicalRecoveryError(
                "PostgreSQL PITR profile requires a WAL archive"
            )
        if (
            self.recovery_target_kind in _POINT_IN_TIME_KINDS
            and self.backup_method != "pitr"
        ):
            raise PostgresPhysicalRecoveryError(
                "PostgreSQL point-in-time target requires a PITR profile"
            )

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable physical recovery profile schema."""
        return {
            "schema_version": 1,
            "postgres_major": self.postgres_major,
            "backup_method": self.backup_method,
            "recovery_target_kind": self.recovery_target_kind,
            "wal_archive_required": self.wal_archive_required,
            "isolated_target_prepared": self.isolated_target_prepared,
            "rpo_seconds": self.rpo_seconds,
            "rto_seconds": self.rto_seconds,
            "package_capability_claim": False,
        }

    def to_json(self) -> str:
        """Return deterministic compact JSON without deployment or business content."""
        return json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )


def bind_postgres_physical_recovery_profile(
    *,
    postgres_major: int,
    backup_method: str,
    recovery_target_kind: str,
    wal_archive_required: bool,
    isolated_target_prepared: bool,
    rpo_seconds: int | None = None,
    rto_seconds: int | None = None,
) -> PostgresPhysicalRecoveryProfile:
    """Bind one caller-owned physical or PITR profile without executing recovery.

    Callers must already have an isolated recovery target. The service name,
    archive path, WAL location, and restore command stay outside this seam.
    ``backup_method="pitr"`` requires ``wal_archive_required=True``. Point-in-time
    kinds ``time``, ``xid``, ``name``, and ``lsn`` require ``backup_method="pitr"``
    so a crash-consistent physical base backup cannot be labeled as a time-flow
    restore. Optional ``rpo_seconds`` and ``rto_seconds`` are deployer-selected
    objectives only; the emitted profile always sets
    ``package_capability_claim`` to ``False``.
    """
    return PostgresPhysicalRecoveryProfile(
        postgres_major=postgres_major,
        backup_method=backup_method,
        recovery_target_kind=recovery_target_kind,
        wal_archive_required=wal_archive_required,
        isolated_target_prepared=isolated_target_prepared,
        rpo_seconds=rpo_seconds,
        rto_seconds=rto_seconds,
    )


def parse_postgres_physical_recovery_profile(
    raw_profile: str,
) -> PostgresPhysicalRecoveryProfile:
    """Parse one bounded profile and reject extensions or capability claims."""
    if type(raw_profile) is not str:
        raise PostgresPhysicalRecoveryError(
            "invalid PostgreSQL physical recovery profile JSON"
        )
    encoded_size = len(raw_profile.encode("utf-8"))
    if encoded_size == 0 or encoded_size > _MAX_PROFILE_JSON_BYTES:
        raise PostgresPhysicalRecoveryError(
            "invalid PostgreSQL physical recovery profile JSON"
        )
    try:
        decoded = json.loads(
            raw_profile,
            object_pairs_hook=_reject_duplicate_object_pairs,
        )
    except (json.JSONDecodeError, RecursionError):
        raise PostgresPhysicalRecoveryError(
            "invalid PostgreSQL physical recovery profile JSON"
        ) from None
    if type(decoded) is not dict or frozenset(decoded) != _PROFILE_KEYS:
        raise PostgresPhysicalRecoveryError(
            "invalid PostgreSQL physical recovery profile schema"
        )
    if decoded.get("schema_version") != 1 or type(decoded.get("schema_version")) is not int:
        raise PostgresPhysicalRecoveryError(
            "invalid PostgreSQL physical recovery profile schema"
        )
    if decoded.get("package_capability_claim") is not False:
        raise PostgresPhysicalRecoveryError(
            "PostgreSQL physical recovery profile cannot claim package capability"
        )
    return PostgresPhysicalRecoveryProfile(
        postgres_major=decoded["postgres_major"],
        backup_method=decoded["backup_method"],
        recovery_target_kind=decoded["recovery_target_kind"],
        wal_archive_required=decoded["wal_archive_required"],
        isolated_target_prepared=decoded["isolated_target_prepared"],
        rpo_seconds=decoded["rpo_seconds"],
        rto_seconds=decoded["rto_seconds"],
    )
