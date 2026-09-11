# SPDX-License-Identifier: Apache-2.0
"""Bound result-materialization regressions for PITR target observation."""

from __future__ import annotations

import pytest

from pg_llm_batch.postgres_physical_recovery import (
    bind_postgres_physical_recovery_profile,
)
from pg_llm_batch.postgres_pitr_target import (
    PostgresPitrRecoveryTarget,
    bind_postgres_pitr_recovery_target,
)
from pg_llm_batch.postgres_recovery_target_configuration import (
    PostgresRecoveryTargetConfigurationObservationError,
    observe_postgres_recovery_target_configuration,
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


class _BoundedCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.requested_size: int | None = None

    def __enter__(self) -> _BoundedCursor:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, _query: str) -> None:
        return None

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.requested_size = size
        return self.rows[:size]


class _Connection:
    def __init__(self, cursor: _BoundedCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _BoundedCursor:
        return self._cursor


def _target() -> PostgresPitrRecoveryTarget:
    profile = bind_postgres_physical_recovery_profile(
        postgres_major=18,
        backup_method="pitr",
        recovery_target_kind="lsn",
        wal_archive_required=True,
        isolated_target_prepared=True,
    )
    return bind_postgres_pitr_recovery_target(
        profile,
        target_value="0/1000000",
        inclusive=True,
        timeline="latest",
    )


def _rows_for(target: PostgresPitrRecoveryTarget) -> list[tuple[object, ...]]:
    settings = {name: "" for name in _SETTING_NAMES}
    for name, value in target.server_settings():
        settings[name] = value
    return [(name, settings[name], False, True) for name in _SETTING_NAMES]


def test_requests_only_one_row_beyond_the_exact_setting_budget() -> None:
    target = _target()
    cursor = _BoundedCursor(_rows_for(target))

    evidence = observe_postgres_recovery_target_configuration(
        _Connection(cursor),
        target=target,
    )

    assert evidence.as_dict()["settings_match"] is True
    assert cursor.requested_size == len(_SETTING_NAMES) + 1


def test_rejects_a_result_page_that_exceeds_the_setting_budget() -> None:
    target = _target()
    rows = _rows_for(target)
    rows.append(("recovery_target", "", False, True))
    cursor = _BoundedCursor(rows)

    with pytest.raises(
        PostgresRecoveryTargetConfigurationObservationError,
        match="evidence is invalid",
    ):
        observe_postgres_recovery_target_configuration(
            _Connection(cursor),
            target=target,
        )

    assert cursor.requested_size == len(_SETTING_NAMES) + 1
