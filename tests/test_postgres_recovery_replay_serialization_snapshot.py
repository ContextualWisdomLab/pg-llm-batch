# SPDX-License-Identifier: Apache-2.0
"""Serialization-snapshot regression for recovery replay observations."""

from __future__ import annotations

import pytest

import pg_llm_batch.postgres_recovery_replay_observation as replay_observation


class _ReplayCursor:
    """Return one fixed paused-recovery observation row."""

    def __enter__(self) -> _ReplayCursor:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: object) -> None:
        if type(sql) is not str:
            raise AssertionError("recovery SQL must remain an exact built-in string")

    def fetchone(self) -> tuple[bool, str, str]:
        return True, "paused", "1/00000020"


class _ReplayConnection:
    """Expose one caller-owned connection seam without DSN authority."""

    def cursor(self) -> _ReplayCursor:
        return _ReplayCursor()


def test_as_dict_serializes_the_already_validated_observation_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serialization must not re-read mutable public fields after provenance validation."""
    evidence = replay_observation.observe_postgres_recovery_replay(
        _ReplayConnection(),
        target_lsn="1/00000010",
    )
    original_require = replay_observation._require_observed

    def validate_then_mutate(
        candidate: replay_observation.PostgresRecoveryReplayObservation,
    ) -> tuple[str, str] | None:
        snapshot = original_require(candidate)
        object.__setattr__(candidate, "target_lsn", "1/00000030")
        object.__setattr__(candidate, "replay_lsn", "1/00000040")
        return snapshot

    monkeypatch.setattr(replay_observation, "_require_observed", validate_then_mutate)

    assert evidence.as_dict() == {
        "target_lsn": "1/00000010",
        "replay_lsn": "1/00000020",
        "recovery_in_progress": True,
        "replay_paused": True,
        "target_reached": True,
    }
