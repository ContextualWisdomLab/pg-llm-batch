# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for post-construction recovery-profile mutation."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pg_llm_batch.postgres_physical_recovery import (
    PostgresPhysicalRecoveryError,
    PostgresPhysicalRecoveryProfile,
)


def _profile() -> PostgresPhysicalRecoveryProfile:
    return PostgresPhysicalRecoveryProfile(
        postgres_major=18,
        backup_method="pitr",
        recovery_target_kind="time",
        wal_archive_required=True,
        isolated_target_prepared=True,
        rpo_seconds=300,
        rto_seconds=3600,
    )


def _as_dict(profile: PostgresPhysicalRecoveryProfile) -> object:
    return profile.as_dict()


def _to_json(profile: PostgresPhysicalRecoveryProfile) -> object:
    return profile.to_json()


@pytest.mark.parametrize("serialize", [_as_dict, _to_json])
def test_serialization_rejects_post_construction_unbounded_metadata(
    serialize: Callable[[PostgresPhysicalRecoveryProfile], object],
) -> None:
    profile = _profile()
    secret_detail = "deployment-secret/" + "x" * 4096
    object.__setattr__(profile, "backup_method", secret_detail)

    with pytest.raises(PostgresPhysicalRecoveryError) as raised:
        serialize(profile)

    assert secret_detail not in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("isolated_target_prepared", False),
        ("wal_archive_required", False),
        ("backup_method", "physical"),
    ],
)
@pytest.mark.parametrize("serialize", [_as_dict, _to_json])
def test_serialization_revalidates_recovery_semantics_after_mutation(
    serialize: Callable[[PostgresPhysicalRecoveryProfile], object],
    field: str,
    value: object,
) -> None:
    profile = _profile()
    object.__setattr__(profile, field, value)

    with pytest.raises(PostgresPhysicalRecoveryError):
        serialize(profile)


@pytest.mark.parametrize("serialize", [_as_dict, _to_json])
def test_serialization_normalizes_deleted_required_field(
    serialize: Callable[[PostgresPhysicalRecoveryProfile], object],
) -> None:
    profile = _profile()
    object.__delattr__(profile, "postgres_major")

    with pytest.raises(
        PostgresPhysicalRecoveryError,
        match="invalid PostgreSQL physical recovery profile",
    ):
        serialize(profile)
