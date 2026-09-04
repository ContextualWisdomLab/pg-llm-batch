# SPDX-License-Identifier: Apache-2.0
"""Review regressions for bounded PostgreSQL PITR target observation."""

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


class _Cursor:
    def __init__(self, rows: object) -> None:
        self.rows = rows
        self.executed: str | None = None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, query: str) -> None:
        self.executed = query

    def fetchall(self) -> object:
        return self.rows


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _Cursor:
        return self._cursor


def _target(
    *,
    kind: str = "lsn",
    target_value: str | None = "0/1000000",
    inclusive: bool | None = True,
) -> PostgresPitrRecoveryTarget:
    profile = bind_postgres_physical_recovery_profile(
        postgres_major=18,
        backup_method="pitr",
        recovery_target_kind=kind,
        wal_archive_required=True,
        isolated_target_prepared=True,
    )
    return bind_postgres_pitr_recovery_target(
        profile,
        target_value=target_value,
        inclusive=inclusive,
        timeline="latest",
    )


def _rows_for(target: PostgresPitrRecoveryTarget) -> list[tuple[object, ...]]:
    settings = {name: "" for name in _SETTING_NAMES}
    for name, value in target.server_settings():
        settings[name] = value
    if target.inclusive is None:
        settings["recovery_target_inclusive"] = "on"
    return [(name, settings[name], False, True) for name in _SETTING_NAMES]


def test_invalid_target_authority_is_rejected_before_database_io() -> None:
    """Reject wrong or mutated target authority before executing the fixed query."""
    target = _target()

    wrong_cursor = _Cursor(_rows_for(target))
    with pytest.raises(PostgresRecoveryTargetConfigurationObservationError):
        observe_postgres_recovery_target_configuration(
            _Connection(wrong_cursor),
            target=object(),
        )
    assert wrong_cursor.executed is None

    object.__setattr__(target, "timeline", "0")
    mutated_cursor = _Cursor([])
    with pytest.raises(PostgresRecoveryTargetConfigurationObservationError):
        observe_postgres_recovery_target_configuration(
            _Connection(mutated_cursor),
            target=target,
        )
    assert mutated_cursor.executed is None


@pytest.mark.parametrize(
    ("kind", "target_value", "inclusive"),
    [
        ("immediate", None, None),
        ("xid", "42", False),
        ("time", "2026-08-21T12:00:00+00:00", False),
    ],
)
def test_observes_supported_target_variants_without_query_value_disclosure(
    kind: str,
    target_value: str | None,
    inclusive: bool | None,
) -> None:
    """Exercise immediate and exclusive point-in-time target observation paths."""
    target = _target(
        kind=kind,
        target_value=target_value,
        inclusive=inclusive,
    )
    cursor = _Cursor(_rows_for(target))

    evidence = observe_postgres_recovery_target_configuration(
        _Connection(cursor),
        target=target,
    )

    assert evidence.as_dict() == {
        "recovery_in_progress": True,
        "settings_match": True,
        "pending_restart": False,
    }
    assert cursor.executed is not None
    if target.target_value is not None:
        assert target.target_value not in cursor.executed


@pytest.mark.parametrize(
    ("setting_size", "expected_message"),
    [
        (1024, "does not match"),
        (1025, "evidence is invalid"),
    ],
)
def test_setting_byte_budget_has_an_exact_1024_byte_boundary(
    setting_size: int,
    expected_message: str,
) -> None:
    """Distinguish the accepted size ceiling from the first oversized setting."""
    target = _target()
    rows = _rows_for(target)
    name, _, pending_restart, recovery_in_progress = rows[0]
    rows[0] = (
        name,
        "x" * setting_size,
        pending_restart,
        recovery_in_progress,
    )

    with pytest.raises(
        PostgresRecoveryTargetConfigurationObservationError,
        match=expected_message,
    ):
        observe_postgres_recovery_target_configuration(
            _Connection(_Cursor(rows)),
            target=target,
        )
