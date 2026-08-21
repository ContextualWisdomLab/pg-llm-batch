# SPDX-License-Identifier: Apache-2.0
"""Recovery-replay observation regressions for an isolated PostgreSQL target."""

from __future__ import annotations

import pytest

from pg_llm_batch.postgres_recovery_replay_observation import (
    PostgresRecoveryReplayObservationError,
    observe_postgres_recovery_replay,
)


class _ReplayCursor:
    """Return one caller-owned recovery observation row."""

    def __init__(self, row: object) -> None:
        self.row = row
        self.executed_sql: str | None = None
        self.execute_calls = 0

    def __enter__(self) -> _ReplayCursor:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: object) -> None:
        if type(sql) is not str:
            raise AssertionError("recovery SQL must be an exact built-in string")
        self.executed_sql = sql
        self.execute_calls += 1

    def fetchone(self) -> object:
        return self.row


class _ReplayConnection:
    """Expose one caller-owned PostgreSQL connection without DSN authority."""

    def __init__(self, row: object) -> None:
        self.cursor_handle = _ReplayCursor(row)
        self.cursor_calls = 0

    def cursor(self) -> _ReplayCursor:
        self.cursor_calls += 1
        return self.cursor_handle


class _FailingCursor(_ReplayCursor):
    """Leak deployment text if the package reflects lower-layer diagnostics."""

    def execute(self, sql: object) -> None:
        del sql
        raise RuntimeError("password=supersecret host=restore.internal")


class _FailingConnection(_ReplayConnection):
    """Return a cursor whose fixed inspection query fails."""

    def cursor(self) -> _ReplayCursor:
        self.cursor_calls += 1
        return _FailingCursor(None)


class _HostileString(str):
    """Refuse rendering if rejected database text reaches diagnostics."""

    def __str__(self) -> str:
        raise AssertionError("hostile database text must not be rendered")


def test_observe_recovery_replay_accepts_paused_target_at_or_beyond_lsn() -> None:
    connection = _ReplayConnection((True, "paused", "1/00000020"))

    evidence = observe_postgres_recovery_replay(
        connection,
        target_lsn="1/00000010",
    )

    assert evidence.target_lsn == "1/00000010"
    assert evidence.replay_lsn == "1/00000020"
    assert evidence.recovery_in_progress is True
    assert evidence.replay_paused is True
    assert evidence.target_reached is True
    assert evidence.as_dict() == {
        "target_lsn": "1/00000010",
        "replay_lsn": "1/00000020",
        "recovery_in_progress": True,
        "replay_paused": True,
        "target_reached": True,
    }


def test_observe_recovery_replay_accepts_exact_target_lsn() -> None:
    evidence = observe_postgres_recovery_replay(
        _ReplayConnection((True, "paused", "A/000000FF")),
        target_lsn="A/000000FF",
    )

    assert evidence.replay_lsn == evidence.target_lsn
    assert evidence.target_reached is True


@pytest.mark.parametrize(
    "target_lsn",
    [
        object(),
        _HostileString("1/00000010"),
        "",
        "01/00000010",
        "1/10",
        "1/0000000a",
        "0/00000000",
    ],
)
def test_observe_recovery_replay_rejects_invalid_target_before_database_io(
    target_lsn: object,
) -> None:
    connection = _ReplayConnection((True, "paused", "1/00000020"))

    with pytest.raises(
        PostgresRecoveryReplayObservationError,
        match="invalid PostgreSQL recovery replay observation inputs",
    ):
        observe_postgres_recovery_replay(connection, target_lsn=target_lsn)  # type: ignore[arg-type]

    assert connection.cursor_calls == 0


def test_observe_recovery_replay_uses_fixed_catalog_qualified_query() -> None:
    connection = _ReplayConnection((True, "paused", "1/00000010"))

    observe_postgres_recovery_replay(connection, target_lsn="1/00000010")

    sql = connection.cursor_handle.executed_sql
    assert sql is not None
    assert connection.cursor_handle.execute_calls == 1
    assert "pg_catalog.pg_is_in_recovery()" in sql
    assert "pg_catalog.pg_get_wal_replay_pause_state()" in sql
    assert "pg_catalog.pg_last_wal_replay_lsn()" in sql
    assert "%s" not in sql


def test_observe_recovery_replay_hides_database_diagnostics() -> None:
    connection = _FailingConnection(None)

    with pytest.raises(
        PostgresRecoveryReplayObservationError,
        match="PostgreSQL recovery replay state could not be inspected",
    ) as raised:
        observe_postgres_recovery_replay(connection, target_lsn="1/00000010")

    assert "supersecret" not in str(raised.value)
    assert "restore.internal" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "row",
    [
        None,
        [True, "paused", "1/00000010"],
        (True, "paused"),
        (1, "paused", "1/00000010"),
        (True, _HostileString("paused"), "1/00000010"),
        (True, "paused", _HostileString("1/00000010")),
        (True, "paused", "01/00000010"),
        (True, "paused", "0/00000000"),
    ],
)
def test_observe_recovery_replay_rejects_malformed_database_evidence(
    row: object,
) -> None:
    with pytest.raises(
        PostgresRecoveryReplayObservationError,
        match="PostgreSQL recovery replay evidence is invalid",
    ):
        observe_postgres_recovery_replay(
            _ReplayConnection(row),
            target_lsn="1/00000010",
        )


def test_observe_recovery_replay_requires_recovery_to_still_be_in_progress() -> None:
    with pytest.raises(
        PostgresRecoveryReplayObservationError,
        match="PostgreSQL recovery target is not in recovery",
    ):
        observe_postgres_recovery_replay(
            _ReplayConnection((False, "paused", "1/00000010")),
            target_lsn="1/00000010",
        )


@pytest.mark.parametrize("pause_state", ["not paused", "pause requested"])
def test_observe_recovery_replay_requires_actual_paused_state(
    pause_state: str,
) -> None:
    with pytest.raises(
        PostgresRecoveryReplayObservationError,
        match="PostgreSQL recovery target is not paused",
    ):
        observe_postgres_recovery_replay(
            _ReplayConnection((True, pause_state, "1/00000010")),
            target_lsn="1/00000010",
        )


def test_observe_recovery_replay_rejects_replay_position_before_target() -> None:
    with pytest.raises(
        PostgresRecoveryReplayObservationError,
        match="PostgreSQL recovery target has not been replayed",
    ):
        observe_postgres_recovery_replay(
            _ReplayConnection((True, "paused", "1/0000000F")),
            target_lsn="1/00000010",
        )
