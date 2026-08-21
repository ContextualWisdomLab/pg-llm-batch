# SPDX-License-Identifier: Apache-2.0
"""Observe bounded WAL replay progress on a paused PostgreSQL recovery target."""

from __future__ import annotations

import re
from dataclasses import dataclass


_LSN_RE = re.compile(r"(?:0|[1-9A-F][0-9A-F]{0,7})/[0-9A-F]{8}\Z")
_REPLAY_SQL = """
SELECT
    pg_catalog.pg_is_in_recovery(),
    pg_catalog.pg_get_wal_replay_pause_state(),
    pg_catalog.pg_last_wal_replay_lsn()::pg_catalog.text
""".strip()


class PostgresRecoveryReplayObservationError(ValueError):
    """Report a fail-closed PostgreSQL recovery replay observation violation."""


@dataclass(frozen=True, slots=True)
class PostgresRecoveryReplayObservation:
    """Represent one content-free paused recovery replay observation.

    The record proves only what ``observe_postgres_recovery_replay`` observed
    through the caller-owned connection: recovery was still active, replay was
    actually paused, and the last replayed WAL location was at or beyond the
    requested LSN. It does not prove that the configured recovery target was
    exact, that the archive is complete, that the timeline is correct, that the
    target is application-ready, or that any RPO/RTO objective is achieved.
    """

    target_lsn: str
    replay_lsn: str

    @property
    def recovery_in_progress(self) -> bool:
        """Return the recovery-state predicate required by this observation."""
        return True

    @property
    def replay_paused(self) -> bool:
        """Return the actual pause-state predicate required by this observation."""
        return True

    @property
    def target_reached(self) -> bool:
        """Return the bounded replay-progress predicate established on creation."""
        return True

    def as_dict(self) -> dict[str, object]:
        """Return the stable content-free machine-readable observation schema."""
        return {
            "target_lsn": self.target_lsn,
            "replay_lsn": self.replay_lsn,
            "recovery_in_progress": True,
            "replay_paused": True,
            "target_reached": True,
        }


def _lsn_position(value: object) -> int | None:
    """Return a canonical nonzero PostgreSQL LSN as a uint64 position."""
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
    return PostgresRecoveryReplayObservation(
        target_lsn=target_lsn,
        replay_lsn=replay_lsn,
    )


def observe_postgres_recovery_replay(
    connection: object,
    *,
    target_lsn: str,
) -> PostgresRecoveryReplayObservation:
    """Observe that an isolated recovery target replayed at least one target LSN.

    ``connection`` is caller-owned and already connected to the isolated
    PostgreSQL target. ``target_lsn`` must be canonical nonzero PostgreSQL LSN
    text. The function performs one fixed, catalog-qualified read-only query and
    requires three conditions in the same returned row: recovery is still in
    progress, ``pg_get_wal_replay_pause_state()`` reports ``paused`` rather than
    merely a pause request, and ``pg_last_wal_replay_lsn()`` is at or beyond the
    requested LSN.

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
