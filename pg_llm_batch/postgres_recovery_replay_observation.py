# SPDX-License-Identifier: Apache-2.0
"""Observe bounded WAL replay progress on a paused PostgreSQL recovery target."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary


_LSN_RE = re.compile(r"(?:0|[1-9A-F][0-9A-F]{0,7})/[0-9A-F]{1,8}\Z")
_REPLAY_SQL = """
SELECT
    pg_catalog.pg_is_in_recovery(),
    pg_catalog.pg_get_wal_replay_pause_state(),
    pg_catalog.pg_last_wal_replay_lsn()::pg_catalog.text
""".strip()
_REPLAY_OBSERVATION_MARK = object()
_OBSERVED_REPLAY: WeakKeyDictionary[
    PostgresRecoveryReplayObservation, tuple[str, str]
] = WeakKeyDictionary()


class PostgresRecoveryReplayObservationError(ValueError):
    """Report a fail-closed PostgreSQL recovery replay observation violation."""


@dataclass(frozen=True, eq=False)
class PostgresRecoveryReplayObservation:
    """Represent one content-free paused recovery replay observation.

    Only ``observe_postgres_recovery_replay`` registers an object as observed.
    Public construction, copying, or post-construction field mutation therefore
    cannot be reused as package inspection provenance. The record proves only
    what the caller-owned connection returned: recovery was still active,
    replay was actually paused, and the last replayed WAL location was at or
    beyond the requested LSN. It does not prove exact recovery-target semantics,
    archive completeness, timeline correctness, application readiness, or an
    achieved RPO/RTO objective.
    """

    target_lsn: str
    replay_lsn: str
    _observation_mark: object = field(default=None, repr=False, compare=False)

    @property
    def recovery_in_progress(self) -> bool:
        """Return the recovery-state predicate from a live observed record."""
        _require_observed(self)
        return True

    @property
    def replay_paused(self) -> bool:
        """Return the actual pause-state predicate from a live observed record."""
        _require_observed(self)
        return True

    @property
    def target_reached(self) -> bool:
        """Return the bounded replay-progress predicate from a live record."""
        _require_observed(self)
        return True

    def as_dict(self) -> dict[str, object]:
        """Return the stable content-free machine-readable observation schema."""
        target_lsn, replay_lsn = _require_observed(self)
        return {
            "target_lsn": target_lsn,
            "replay_lsn": replay_lsn,
            "recovery_in_progress": True,
            "replay_paused": True,
            "target_reached": True,
        }


def postgres_recovery_replay_observation_was_observed(evidence: object) -> bool:
    """Return whether one exact live object still matches its observed snapshot."""
    if type(evidence) is not PostgresRecoveryReplayObservation:
        return False
    observed = _OBSERVED_REPLAY.get(evidence)
    if observed is None:
        return False
    observed_target_lsn, observed_replay_lsn = observed
    return (
        evidence._observation_mark,
        evidence.target_lsn,
        evidence.replay_lsn,
    ) == (
        _REPLAY_OBSERVATION_MARK,
        observed_target_lsn,
        observed_replay_lsn,
    )


def _require_observed(
    evidence: PostgresRecoveryReplayObservation,
) -> tuple[str, str]:
    """Return the validated immutable observation snapshot or fail closed."""
    if not postgres_recovery_replay_observation_was_observed(evidence):
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay observation provenance is invalid"
        )
    observed = _OBSERVED_REPLAY.get(evidence)
    if observed is None:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay observation provenance is invalid"
        )
    return observed


def _record_observed_replay(evidence: PostgresRecoveryReplayObservation) -> None:
    """Remember the exact live observation object and its immutable field snapshot."""
    _OBSERVED_REPLAY[evidence] = (evidence.target_lsn, evidence.replay_lsn)


def _lsn_position(value: object) -> int | None:
    """Return a normalized nonzero PostgreSQL LSN as a uint64 position."""
    if type(value) is not str:
        return None
    if _LSN_RE.fullmatch(value) is None:
        return None
    high_text, low_text = value.split("/", 1)
    position = (int(high_text, 16) << 32) | int(low_text, 16)
    if position == 0:
        return None
    return position


def _evaluate_replay_row(
    row: object,
    *,
    target_lsn: str,
    target_position: int,
) -> PostgresRecoveryReplayObservation:
    """Validate one finite PostgreSQL recovery observation row."""
    if type(row) is not tuple:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay evidence is invalid"
        )
    if len(row) != 3:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay evidence is invalid"
        )
    recovery_in_progress, pause_state, replay_lsn = row
    if type(recovery_in_progress) is not bool:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay evidence is invalid"
        )
    if type(pause_state) is not str:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay evidence is invalid"
        )
    replay_position = _lsn_position(replay_lsn)
    if replay_position is None:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay evidence is invalid"
        )
    if not recovery_in_progress:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery target is not in recovery"
        )
    if pause_state != "paused":
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery target is not paused"
        )
    if replay_position < target_position:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery target has not been replayed"
        )
    evidence = PostgresRecoveryReplayObservation(
        target_lsn=target_lsn,
        replay_lsn=replay_lsn,
        _observation_mark=_REPLAY_OBSERVATION_MARK,
    )
    _record_observed_replay(evidence)
    return evidence


def observe_postgres_recovery_replay(
    connection: object,
    *,
    target_lsn: str,
) -> PostgresRecoveryReplayObservation:
    """Observe that an isolated recovery target replayed at least one target LSN.

    ``connection`` is caller-owned and already connected to the isolated
    PostgreSQL target. ``target_lsn`` must be normalized uppercase nonzero
    PostgreSQL LSN text with at most eight hexadecimal digits per segment. The
    function performs one fixed, catalog-qualified read-only query and requires
    three conditions in the same returned row: recovery is still in progress,
    ``pg_get_wal_replay_pause_state()`` reports ``paused`` rather than merely a
    pause request, and ``pg_last_wal_replay_lsn()`` is at or beyond the requested
    LSN.

    PostgreSQL documents LSNs as monotonically increasing WAL byte positions and
    documents the ``paused`` state as the state in which no further database
    changes are applied until replay resumes. Consequently this is a bounded
    replay-progress/acceptance-window observation only. It does not start or
    configure PostgreSQL, create ``recovery.signal``, install ``restore_command``,
    validate WAL bytes or timeline ancestry, prove exact stop-target semantics,
    resume or promote recovery, prove application readiness, recover external
    secrets, or establish RPO/RTO, HA/DR, CSAP, SOC 2, or certification claims.
    """
    target_position = _lsn_position(target_lsn)
    if target_position is None:
        raise PostgresRecoveryReplayObservationError(
            "invalid PostgreSQL recovery replay observation inputs"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute(_REPLAY_SQL)
            row = cursor.fetchone()
    except Exception:
        raise PostgresRecoveryReplayObservationError(
            "PostgreSQL recovery replay state could not be inspected"
        ) from None
    return _evaluate_replay_row(
        row,
        target_lsn=target_lsn,
        target_position=target_position,
    )
