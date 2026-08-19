# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for deterministic PostgreSQL PITR target selection."""

from __future__ import annotations

import pytest

from pg_llm_batch.postgres_physical_recovery import (
    PostgresPhysicalRecoveryProfile,
    bind_postgres_physical_recovery_profile,
)
from pg_llm_batch.postgres_pitr_target import (
    PostgresPitrTargetError,
    bind_postgres_pitr_recovery_target,
)


def _profile(**overrides: object) -> PostgresPhysicalRecoveryProfile:
    arguments: dict[str, object] = {
        "postgres_major": 18,
        "backup_method": "pitr",
        "recovery_target_kind": "time",
        "wal_archive_required": True,
        "isolated_target_prepared": True,
        "rpo_seconds": 300,
        "rto_seconds": 3600,
    }
    arguments.update(overrides)
    return bind_postgres_physical_recovery_profile(**arguments)  # type: ignore[arg-type]


def test_time_target_is_normalized_to_utc_and_pauses_for_acceptance() -> None:
    """Time recovery is timezone-explicit, deterministic, and never auto-promotes."""
    target = bind_postgres_pitr_recovery_target(
        _profile(),
        target_value="2026-08-18T01:02:03.456789+09:00",
        inclusive=False,
        timeline="latest",
    )

    assert target.target_kind == "time"
    assert target.target_value == "2026-08-17T16:02:03.456789+00:00"
    assert target.inclusive is False
    assert target.timeline == "latest"
    assert target.recovery_target_action == "pause"
    assert target.server_settings() == (
        ("recovery_target_time", "2026-08-17T16:02:03.456789+00:00"),
        ("recovery_target_inclusive", "off"),
        ("recovery_target_timeline", "latest"),
        ("recovery_target_action", "pause"),
    )


def test_lsn_target_is_canonical_and_accepts_reviewed_numeric_timeline() -> None:
    """An LSN target is uppercase canonical evidence with an explicit inclusion edge."""
    target = bind_postgres_pitr_recovery_target(
        _profile(recovery_target_kind="lsn"),
        target_value="16/b374d848",
        inclusive=True,
        timeline=17,
    )

    assert target.target_value == "16/B374D848"
    assert target.timeline == "17"
    assert target.server_settings() == (
        ("recovery_target_lsn", "16/B374D848"),
        ("recovery_target_inclusive", "on"),
        ("recovery_target_timeline", "17"),
        ("recovery_target_action", "pause"),
    )


def test_xid_target_is_bounded_and_explicitly_inclusive() -> None:
    """A normal transaction ID target preserves the caller's reviewed stop edge."""
    target = bind_postgres_pitr_recovery_target(
        _profile(recovery_target_kind="xid"),
        target_value="4294967295",
        inclusive=False,
        timeline="current",
    )

    assert target.target_value == "4294967295"
    assert target.server_settings()[1] == ("recovery_target_inclusive", "off")


def test_named_restore_point_omits_inclusive_setting() -> None:
    """Named restore points are exact bounded text and have no inclusive toggle."""
    target = bind_postgres_pitr_recovery_target(
        _profile(recovery_target_kind="name"),
        target_value="before_customer_migration_2026_08_18",
        inclusive=None,
        timeline="latest",
    )

    assert target.server_settings() == (
        ("recovery_target_name", "before_customer_migration_2026_08_18"),
        ("recovery_target_timeline", "latest"),
        ("recovery_target_action", "pause"),
    )


def test_immediate_target_has_no_value_or_inclusive_setting() -> None:
    """Immediate recovery stops at backup consistency and still pauses acceptance."""
    target = bind_postgres_pitr_recovery_target(
        _profile(recovery_target_kind="immediate"),
        target_value=None,
        inclusive=None,
        timeline="latest",
    )

    assert target.target_value is None
    assert target.inclusive is None
    assert target.server_settings() == (
        ("recovery_target", "immediate"),
        ("recovery_target_timeline", "latest"),
        ("recovery_target_action", "pause"),
    )


def test_binding_requires_exact_reviewed_profile_type() -> None:
    """Duck-typed or subclassed profile authority cannot select recovery settings."""

    class ProfileSubclass(PostgresPhysicalRecoveryProfile):
        pass

    with pytest.raises(PostgresPitrTargetError, match="^invalid PostgreSQL PITR profile$"):
        bind_postgres_pitr_recovery_target(  # type: ignore[arg-type]
            object(), target_value=None, inclusive=None, timeline="latest"
        )

    with pytest.raises(PostgresPitrTargetError, match="^invalid PostgreSQL PITR profile$"):
        bind_postgres_pitr_recovery_target(
            ProfileSubclass(
                postgres_major=18,
                backup_method="pitr",
                recovery_target_kind="immediate",
                wal_archive_required=True,
                isolated_target_prepared=True,
                rpo_seconds=None,
                rto_seconds=None,
            ),
            target_value=None,
            inclusive=None,
            timeline="latest",
        )


def test_binding_requires_pitr_profile_with_archive_and_isolated_target() -> None:
    """A crash-consistent physical profile cannot authorize point-in-time settings."""
    physical = bind_postgres_physical_recovery_profile(
        postgres_major=18,
        backup_method="physical",
        recovery_target_kind="immediate",
        wal_archive_required=False,
        isolated_target_prepared=True,
    )
    with pytest.raises(
        PostgresPitrTargetError,
        match="^PostgreSQL PITR target requires a PITR profile with WAL archive$",
    ):
        bind_postgres_pitr_recovery_target(
            physical, target_value=None, inclusive=None, timeline="latest"
        )


@pytest.mark.parametrize(
    ("kind", "target_value", "inclusive"),
    [
        ("immediate", "16/B374D848", None),
        ("immediate", None, True),
        ("time", "2026-08-18T01:02:03", True),
        ("time", "not-a-time", True),
        ("time", "2026-08-18T01:02:03+09:00", None),
        ("time", "2026-08-18T01:02:03+09:00", 1),
        ("xid", "2", True),
        ("xid", "042", True),
        ("xid", "4294967296", True),
        ("xid", 42, True),
        ("lsn", "0/0", True),
        ("lsn", "16-GOOD", True),
        ("lsn", "100000000/1", True),
        ("name", "", None),
        ("name", "bad\nname", None),
        ("name", "x" * 257, None),
        ("name", "restore-point", False),
    ],
)
def test_invalid_target_values_fail_closed(
    kind: str, target_value: object, inclusive: object
) -> None:
    """Malformed or semantically mismatched target authority is rejected."""
    with pytest.raises(
        PostgresPitrTargetError,
        match="^invalid PostgreSQL PITR recovery target$",
    ):
        bind_postgres_pitr_recovery_target(
            _profile(recovery_target_kind=kind),
            target_value=target_value,  # type: ignore[arg-type]
            inclusive=inclusive,  # type: ignore[arg-type]
            timeline="latest",
        )


@pytest.mark.parametrize(
    "timeline",
    [0, -1, True, 1 << 32, "17", "0x11", "latest ", "", object()],
)
def test_invalid_timeline_authority_fails_closed(timeline: object) -> None:
    """Only latest/current or an exact positive uint32 timeline is accepted."""
    with pytest.raises(
        PostgresPitrTargetError,
        match="^invalid PostgreSQL PITR recovery timeline$",
    ):
        bind_postgres_pitr_recovery_target(
            _profile(),
            target_value="2026-08-18T01:02:03+09:00",
            inclusive=True,
            timeline=timeline,  # type: ignore[arg-type]
        )


def test_hostile_string_subclasses_are_rejected_before_rendering() -> None:
    """Subclass hooks cannot execute while target authority is being normalized."""

    class HostileString(str):
        def __str__(self) -> str:
            raise AssertionError("must not render hostile target input")

    with pytest.raises(
        PostgresPitrTargetError,
        match="^invalid PostgreSQL PITR recovery target$",
    ):
        bind_postgres_pitr_recovery_target(
            _profile(recovery_target_kind="name"),
            target_value=HostileString("safe-looking"),
            inclusive=None,
            timeline="latest",
        )
    with pytest.raises(
        PostgresPitrTargetError,
        match="^invalid PostgreSQL PITR recovery timeline$",
    ):
        bind_postgres_pitr_recovery_target(
            _profile(),
            target_value="2026-08-18T01:02:03+09:00",
            inclusive=True,
            timeline=HostileString("latest"),
        )
