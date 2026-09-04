# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded observation of effective PostgreSQL PITR target settings."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.postgres_physical_recovery import (
    bind_postgres_physical_recovery_profile,
)
from pg_llm_batch.postgres_pitr_target import (
    PostgresPitrRecoveryTarget,
    bind_postgres_pitr_recovery_target,
)
from pg_llm_batch.postgres_recovery_target_configuration import (
    PostgresRecoveryTargetConfigurationObservation,
    PostgresRecoveryTargetConfigurationObservationError,
    observe_postgres_recovery_target_configuration,
    postgres_recovery_target_configuration_was_observed,
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
    def __init__(
        self,
        rows: object,
        *,
        execute_error: Exception | None = None,
        fetch_error: Exception | None = None,
    ) -> None:
        self.rows = rows
        self.execute_error = execute_error
        self.fetch_error = fetch_error
        self.executed: str | None = None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, query: str) -> None:
        self.executed = query
        if self.execute_error is not None:
            raise self.execute_error

    def fetchall(self) -> object:
        if self.fetch_error is not None:
            raise self.fetch_error
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
    timeline: str | int = "latest",
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
        timeline=timeline,
    )


def _rows_for(target: PostgresPitrRecoveryTarget) -> list[tuple[object, ...]]:
    settings = {name: "" for name in _SETTING_NAMES}
    if target.target_kind == "immediate":
        settings["recovery_target"] = "immediate"
    else:
        settings[f"recovery_target_{target.target_kind}"] = target.target_value or ""
    settings["recovery_target_inclusive"] = (
        "on" if target.inclusive is None or target.inclusive else "off"
    )
    settings["recovery_target_timeline"] = target.timeline
    settings["recovery_target_action"] = "pause"
    return [(name, settings[name], False, True) for name in _SETTING_NAMES]


def _observe(
    target: PostgresPitrRecoveryTarget,
    rows: object,
    *,
    execute_error: Exception | None = None,
    fetch_error: Exception | None = None,
) -> tuple[PostgresRecoveryTargetConfigurationObservation, _Cursor]:
    cursor = _Cursor(
        rows,
        execute_error=execute_error,
        fetch_error=fetch_error,
    )
    evidence = observe_postgres_recovery_target_configuration(
        _Connection(cursor),
        target=target,
    )
    return evidence, cursor


def test_observes_exact_effective_target_without_exposing_target_content() -> None:
    target = _target()
    evidence, cursor = _observe(target, _rows_for(target))

    assert postgres_recovery_target_configuration_was_observed(evidence)
    assert evidence.as_dict() == {
        "recovery_in_progress": True,
        "settings_match": True,
        "pending_restart": False,
    }
    assert cursor.executed is not None
    assert "pg_catalog.pg_settings" in cursor.executed
    assert "pg_catalog.pg_is_in_recovery()" in cursor.executed
    assert target.target_value not in cursor.executed
    for setting_name in _SETTING_NAMES:
        assert setting_name in cursor.executed


def test_default_inclusive_setting_is_verified_when_target_omits_it() -> None:
    target = _target(kind="name", target_value="buyer-acceptance", inclusive=None)

    evidence, _ = _observe(target, _rows_for(target))

    assert evidence.as_dict()["settings_match"] is True


@pytest.mark.parametrize(
    "case",
    [
        "not-list",
        "wrong-row-count",
        "not-tuple-row",
        "wrong-row-width",
        "name-type",
        "setting-type",
        "pending-type",
        "recovery-type",
        "unknown-name",
        "duplicate-name",
        "unencodable-setting",
        "oversized-setting",
    ],
)
def test_rejects_malformed_or_ambiguous_setting_rows(case: str) -> None:
    target = _target()
    rows: object = _rows_for(target)
    assert isinstance(rows, list)

    if case == "not-list":
        rows = tuple(rows)
    elif case == "wrong-row-count":
        rows = rows[:-1]
    elif case == "not-tuple-row":
        rows[0] = list(rows[0])
    elif case == "wrong-row-width":
        rows[0] = rows[0][:-1]
    elif case == "name-type":
        rows[0] = (1, rows[0][1], False, True)
    elif case == "setting-type":
        rows[0] = (rows[0][0], 1, False, True)
    elif case == "pending-type":
        rows[0] = (rows[0][0], rows[0][1], 0, True)
    elif case == "recovery-type":
        rows[0] = (rows[0][0], rows[0][1], False, 1)
    elif case == "unknown-name":
        rows[0] = ("application_name", rows[0][1], False, True)
    elif case == "duplicate-name":
        rows[-1] = rows[0]
    elif case == "unencodable-setting":
        rows[0] = (rows[0][0], "\ud800", False, True)
    else:
        rows[0] = (rows[0][0], "x" * 1025, False, True)

    with pytest.raises(PostgresRecoveryTargetConfigurationObservationError):
        _observe(target, rows)


def test_rejects_pending_restart_configuration() -> None:
    target = _target()
    rows = _rows_for(target)
    name, setting, _, recovery = rows[0]
    rows[0] = (name, setting, True, recovery)

    with pytest.raises(
        PostgresRecoveryTargetConfigurationObservationError,
        match="pending restart",
    ):
        _observe(target, rows)


def test_rejects_target_that_is_no_longer_in_recovery() -> None:
    target = _target()
    rows = _rows_for(target)
    name, setting, pending, _ = rows[0]
    rows[0] = (name, setting, pending, False)

    with pytest.raises(
        PostgresRecoveryTargetConfigurationObservationError,
        match="not in recovery",
    ):
        _observe(target, rows)


def test_rejects_effective_setting_mismatch() -> None:
    target = _target()
    rows = _rows_for(target)
    name, _, pending, recovery = rows[3]
    rows[3] = (name, "0/2000000", pending, recovery)

    with pytest.raises(
        PostgresRecoveryTargetConfigurationObservationError,
        match="does not match",
    ):
        _observe(target, rows)


def test_rejects_wrong_or_mutated_target_authority() -> None:
    target = _target()

    with pytest.raises(PostgresRecoveryTargetConfigurationObservationError):
        observe_postgres_recovery_target_configuration(
            _Connection(_Cursor(_rows_for(target))),
            target=object(),
        )

    object.__setattr__(target, "timeline", "0")
    with pytest.raises(PostgresRecoveryTargetConfigurationObservationError):
        observe_postgres_recovery_target_configuration(
            _Connection(_Cursor([])),
            target=target,
        )


def test_redacts_database_and_transport_failures() -> None:
    target = _target()

    for kwargs in (
        {"execute_error": RuntimeError("postgres://secret@host/db")},
        {"fetch_error": RuntimeError("postgres://secret@host/db")},
    ):
        with pytest.raises(PostgresRecoveryTargetConfigurationObservationError) as exc_info:
            _observe(target, _rows_for(target), **kwargs)
        assert "secret" not in str(exc_info.value)
        assert "host" not in str(exc_info.value)


def test_only_exact_live_observation_object_retains_provenance() -> None:
    target = _target()
    observed, _ = _observe(target, _rows_for(target))

    fabricated = PostgresRecoveryTargetConfigurationObservation()
    assert not postgres_recovery_target_configuration_was_observed(fabricated)
    with pytest.raises(PostgresRecoveryTargetConfigurationObservationError):
        fabricated.as_dict()

    copied = replace(observed)
    assert not postgres_recovery_target_configuration_was_observed(copied)

    class _Derived(PostgresRecoveryTargetConfigurationObservation):
        pass

    derived = _Derived()
    assert not postgres_recovery_target_configuration_was_observed(derived)

    object.__setattr__(observed, "settings_match", False)
    assert not postgres_recovery_target_configuration_was_observed(observed)
    with pytest.raises(PostgresRecoveryTargetConfigurationObservationError):
        observed.as_dict()
