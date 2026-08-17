# SPDX-License-Identifier: Apache-2.0
"""Hardening regressions for deterministic PostgreSQL PITR target evidence."""

from __future__ import annotations

import pytest

from pg_llm_batch.postgres_pitr_target import (
    PostgresPitrRecoveryTarget,
    PostgresPitrTargetError,
)


def test_direct_target_rejects_hostile_action_without_comparison() -> None:
    """Subclass comparison hooks cannot execute while action authority is validated."""

    class HostileString(str):
        def __eq__(self, other: object) -> bool:
            raise AssertionError("must not compare hostile action metadata")

        def __ne__(self, other: object) -> bool:
            raise AssertionError("must not compare hostile action metadata")

    with pytest.raises(
        PostgresPitrTargetError,
        match="^invalid PostgreSQL PITR recovery target$",
    ):
        PostgresPitrRecoveryTarget(
            target_kind="immediate",
            target_value=None,
            inclusive=None,
            timeline="latest",
            recovery_target_action=HostileString("pause"),
        )


@pytest.mark.parametrize(
    ("target_kind", "target_value", "inclusive", "timeline"),
    [
        (object(), None, None, "latest"),
        ("immediate", None, None, 1),
        ("immediate", None, None, "not-a-timeline"),
        ("immediate", None, None, "01"),
        ("immediate", None, None, "4294967296"),
        ("unknown", None, None, "latest"),
        ("lsn", "16/b374d848", True, "latest"),
        ("time", "2026-02-31T01:02:03+09:00", True, "latest"),
        ("time", "\ud800", True, "latest"),
        ("name", "\ud800", None, "latest"),
        ("name", "restore-point", True, "latest"),
    ],
)
def test_direct_target_rejects_noncanonical_or_invalid_evidence(
    target_kind: object,
    target_value: object,
    inclusive: object,
    timeline: object,
) -> None:
    """Direct construction cannot bypass canonical target validation."""
    with pytest.raises(
        PostgresPitrTargetError,
        match="^invalid PostgreSQL PITR recovery target$",
    ):
        PostgresPitrRecoveryTarget(  # type: ignore[arg-type]
            target_kind=target_kind,
            target_value=target_value,
            inclusive=inclusive,
            timeline=timeline,
        )
