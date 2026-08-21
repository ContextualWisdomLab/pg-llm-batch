# SPDX-License-Identifier: Apache-2.0
"""Observe effective PostgreSQL PITR target settings without mutating recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from .postgres_pitr_target import (
    PostgresPitrRecoveryTarget,
    PostgresPitrTargetError,
)


_SETTING_NAMES = (
    "recovery_target",
    "recovery_target_action",
    "recovery_target_inclusive",
    "recovery_target_lsn",
    "recovery_target_name",
    "recovery_target_time",
    "recovery_target_timeline",
    "recovery_target_xid",
)
_MAX_SETTING_BYTES = 1024
_TARGET_CONFIGURATION_SQL = """
SELECT
    s.name::pg_catalog.text,
    s.setting::pg_catalog.text,
    s.pending_restart,
    pg_catalog.pg_is_in_recovery()
FROM pg_catalog.pg_settings AS s
WHERE s.name IN (
    'recovery_target',
    'recovery_target_action',
    'recovery_target_inclusive',
    'recovery_target_lsn',
    'recovery_target_name',
    'recovery_target_time',
    'recovery_target_timeline',
    'recovery_target_xid'
)
ORDER BY s.name
""".strip()
_OBSERVATION_MARK = object()


class PostgresRecoveryTargetConfigurationObservationError(ValueError):
    """Report a fail-closed PostgreSQL recovery-target observation violation."""


@dataclass(frozen=True, eq=False)
class PostgresRecoveryTargetConfigurationObservation:
    """Represent one content-free live match of effective PITR target settings.

    Only :func:`observe_postgres_recovery_target_configuration` registers an
    object as package-observed evidence. Public construction, copying,
    subclassing, or post-construction field mutation therefore cannot be reused
    as observation provenance. The record intentionally contains no recovery
    target value, restore-point name, timeline identifier, connection detail,
    filesystem path, or credential.
    """

    recovery_in_progress: bool = True
    settings_match: bool = True
    pending_restart: bool = False
    _observation_mark: object = field(default=None, repr=False, compare=False)

    def as_dict(self) -> dict[str, bool]:
        """Return stable content-free predicates from a live observed record."""
        recovery_in_progress, settings_match, pending_restart = _require_observed(self)
        return {
            "recovery_in_progress": recovery_in_progress,
            "settings_match": settings_match,
            "pending_restart": pending_restart,
        }


_OBSERVED_CONFIGURATION: WeakKeyDictionary[
    PostgresRecoveryTargetConfigurationObservation, tuple[bool, bool, bool]
] = WeakKeyDictionary()


def postgres_recovery_target_configuration_was_observed(evidence: object) -> bool:
    """Return whether one exact live object still matches its observed snapshot."""
    if type(evidence) is not PostgresRecoveryTargetConfigurationObservation:
        return False
    observed = _OBSERVED_CONFIGURATION.get(evidence)
    return observed is not None and (
        evidence._observation_mark,
        evidence.recovery_in_progress,
        evidence.settings_match,
        evidence.pending_restart,
    ) == (_OBSERVATION_MARK, *observed)


def _require_observed(
    evidence: PostgresRecoveryTargetConfigurationObservation,
) -> tuple[bool, bool, bool]:
    """Return the immutable observation snapshot or fail closed."""
    if not postgres_recovery_target_configuration_was_observed(evidence):
        raise PostgresRecoveryTargetConfigurationObservationError(
            "PostgreSQL recovery target configuration observation provenance is invalid"
        )
    return _OBSERVED_CONFIGURATION[evidence]


def _record_observation(
    evidence: PostgresRecoveryTargetConfigurationObservation,
) -> None:
    """Remember the exact live observation object and its immutable predicates."""
    _OBSERVED_CONFIGURATION[evidence] = (
        evidence.recovery_in_progress,
        evidence.settings_match,
        evidence.pending_restart,
    )


def _snapshot_target(target: object) -> PostgresPitrRecoveryTarget:
    """Copy one exact reviewed target into a fresh canonical authority snapshot."""
    if type(target) is not PostgresPitrRecoveryTarget:
        raise PostgresRecoveryTargetConfigurationObservationError(
            "invalid PostgreSQL recovery target configuration observation inputs"
        )
    try:
        return PostgresPitrRecoveryTarget(
            target_kind=target.target_kind,
            target_value=target.target_value,
            inclusive=target.inclusive,
            timeline=target.timeline,
            recovery_target_action=target.recovery_target_action,
        )
    except (AttributeError, PostgresPitrTargetError):
        raise PostgresRecoveryTargetConfigurationObservationError(
            "invalid PostgreSQL recovery target configuration observation inputs"
        ) from None


def _expected_settings(target: PostgresPitrRecoveryTarget) -> dict[str, str]:
    """Return the complete effective setting map expected for one target."""
    expected = {name: "" for name in _SETTING_NAMES}
    for name, value in target.server_settings():
        expected[name] = value
    if target.inclusive is None:
        expected["recovery_target_inclusive"] = "on"
    return expected


def _validate_rows(rows: object, expected: dict[str, str]) -> None:
    """Fail closed unless one finite row set exactly matches target authority."""
    if type(rows) is not list or len(rows) != len(_SETTING_NAMES):
        raise PostgresRecoveryTargetConfigurationObservationError(
            "PostgreSQL recovery target configuration evidence is invalid"
        )
    seen: set[str] = set()
    for row in rows:
        if type(row) is not tuple or len(row) != 4:
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target configuration evidence is invalid"
            )
        name, setting, pending_restart, recovery_in_progress = row
        if not (
            type(name) is str
            and type(setting) is str
            and type(pending_restart) is bool
            and type(recovery_in_progress) is bool
        ):
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target configuration evidence is invalid"
            )
        if name not in expected or name in seen:
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target configuration evidence is invalid"
            )
        try:
            setting_size = len(setting.encode("utf-8"))
        except UnicodeError:
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target configuration evidence is invalid"
            ) from None
        if setting_size > _MAX_SETTING_BYTES:
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target configuration evidence is invalid"
            )
        if pending_restart:
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target configuration has pending restart state"
            )
        if not recovery_in_progress:
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target is not in recovery"
            )
        if setting != expected[name]:
            raise PostgresRecoveryTargetConfigurationObservationError(
                "PostgreSQL recovery target configuration does not match target authority"
            )
        seen.add(name)


def observe_postgres_recovery_target_configuration(
    connection: object,
    *,
    target: object,
) -> PostgresRecoveryTargetConfigurationObservation:
    """Observe that effective recovery settings match one reviewed PITR target.

    ``connection`` is caller-owned and already connected to an isolated
    PostgreSQL recovery target. ``target`` must be the exact reviewed
    :class:`PostgresPitrRecoveryTarget` type. The function snapshots that target,
    executes one fixed catalog-qualified read-only query, requires the target to
    remain in recovery with no pending-restart setting state, and compares all
    eight recovery-target settings to the deterministic target authority.

    PostgreSQL's default ``recovery_target_inclusive=on`` is checked explicitly
    when a named or immediate target correctly omits that server setting. The
    returned observation contains only fixed predicates and has live-object
    provenance; target values and connection details are never returned.

    This seam does not write PostgreSQL configuration, create ``recovery.signal``,
    supply ``restore_command``, replay or validate WAL bytes, prove archive or
    timeline ancestry, prove that the target was reached, pause or promote
    recovery, prove application readiness, or establish RPO/RTO, HA/DR, CSAP,
    SOC 2, or certification claims.
    """
    reviewed_target = _snapshot_target(target)
    expected = _expected_settings(reviewed_target)
    try:
        with connection.cursor() as cursor:
            cursor.execute(_TARGET_CONFIGURATION_SQL)
            rows = cursor.fetchall()
    except Exception:
        raise PostgresRecoveryTargetConfigurationObservationError(
            "PostgreSQL recovery target configuration could not be inspected"
        ) from None
    _validate_rows(rows, expected)
    evidence = PostgresRecoveryTargetConfigurationObservation(
        _observation_mark=_OBSERVATION_MARK
    )
    _record_observation(evidence)
    return evidence
