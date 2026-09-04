# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for isolated restore-target service identity."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_restore_target as restore_target
from pg_llm_batch.postgres_restore_target import (
    PostgresRestoreTargetError,
    PostgresRestoreTargetIdentity,
    verify_postgres_restore_target_isolation,
)


LIVE_CLUSTER = 7_438_291_055_661_123_456
RESTORE_CLUSTER = 7_438_291_055_661_123_457


class _HostileServiceName(str):
    """Identify a caller-controlled libpq service-name subclass."""


class _HostileClusterIdentity(PostgresRestoreTargetIdentity):
    """Identify a caller-controlled cluster-identity subclass."""


def _identity(system_identifier: int) -> PostgresRestoreTargetIdentity:
    """Build one exact cluster-identity record for a realistic production pair."""
    return PostgresRestoreTargetIdentity(system_identifier=system_identifier)


def test_operator_can_separate_live_batch_from_isolated_restore_cluster() -> None:
    """A production service and cluster must stay distinct from the restore drill."""
    verify_postgres_restore_target_isolation(
        live_service_name="batch-prod",
        restore_service_name="batch-restore-isolated",
        live_target_identity=_identity(LIVE_CLUSTER),
        restore_target_identity=_identity(RESTORE_CLUSTER),
    )


def test_same_service_name_fails_closed_before_restore() -> None:
    """Restoring into the live service is not an isolated drill."""
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^PostgreSQL restore target is not isolated from the live service$",
    ) as raised:
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name="batch-prod",
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=_identity(RESTORE_CLUSTER),
        )
    assert "batch-prod" not in str(raised.value)
    assert "postgresql://" not in str(raised.value)
    assert "secret" not in str(raised.value)
    assert str(LIVE_CLUSTER) not in str(raised.value)


def test_aliased_service_names_for_the_same_cluster_fail_closed() -> None:
    """A second pg_service name that still points at production is not isolated."""
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^PostgreSQL restore target is not isolated from the live service$",
    ) as raised:
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name="batch-restore-isolated",
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=_identity(LIVE_CLUSTER),
        )
    assert "batch-prod" not in str(raised.value)
    assert "batch-restore-isolated" not in str(raised.value)
    assert "postgresql://" not in str(raised.value)
    assert str(LIVE_CLUSTER) not in str(raised.value)


def test_identity_mutation_after_validation_cannot_authorize_live_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-validation caller mutation cannot change the isolation decision."""
    live_identity = _identity(LIVE_CLUSTER)
    restore_identity = _identity(LIVE_CLUSTER)
    original_validator = restore_target._plain_system_identifier
    validations = 0

    def validate_then_mutate(value: object) -> bool:
        nonlocal validations
        valid = original_validator(value)
        validations += 1
        if validations == 2:
            object.__setattr__(
                restore_identity,
                "system_identifier",
                RESTORE_CLUSTER,
            )
        return valid

    monkeypatch.setattr(
        restore_target,
        "_plain_system_identifier",
        validate_then_mutate,
    )

    with pytest.raises(
        PostgresRestoreTargetError,
        match="^PostgreSQL restore target is not isolated from the live service$",
    ):
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name="batch-restore-isolated",
            live_target_identity=live_identity,
            restore_target_identity=restore_identity,
        )


@pytest.mark.parametrize(
    ("live_service_name", "restore_service_name"),
    [
        ("batch-prod", "postgresql://operator@db/restore"),
        ("postgresql://operator@db/live", "batch-restore-isolated"),
        ("batch-prod", ""),
        ("", "batch-restore-isolated"),
        ("batch-prod", "../restore"),
        ("batch-prod", "batch restore"),
        ("batch-prod", "a" * 65),
    ],
)
def test_dsn_path_and_malformed_names_are_rejected_before_comparison(
    live_service_name: object,
    restore_service_name: object,
) -> None:
    """libpq service names are the only accepted identity; DSNs are not authority."""
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ) as raised:
        verify_postgres_restore_target_isolation(
            live_service_name=live_service_name,  # type: ignore[arg-type]
            restore_service_name=restore_service_name,  # type: ignore[arg-type]
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=_identity(RESTORE_CLUSTER),
        )
    assert "postgresql://" not in str(raised.value)
    assert "secret" not in str(raised.value)
    assert "../" not in str(raised.value)


def test_service_name_subclasses_are_rejected_before_comparison() -> None:
    """Exact built-in strings are the only accepted service-name type."""
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ):
        verify_postgres_restore_target_isolation(
            live_service_name=_HostileServiceName("batch-prod"),
            restore_service_name="batch-restore-isolated",
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=_identity(RESTORE_CLUSTER),
        )
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ):
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name=_HostileServiceName("batch-restore-isolated"),
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=_identity(RESTORE_CLUSTER),
        )


@pytest.mark.parametrize(
    ("live_service_name", "restore_service_name"),
    [
        (SimpleNamespace(name="batch-prod"), "batch-restore-isolated"),
        ("batch-prod", SimpleNamespace(name="batch-restore-isolated")),
        (None, "batch-restore-isolated"),
        ("batch-prod", None),
        (b"batch-prod", "batch-restore-isolated"),
    ],
)
def test_non_string_identities_are_rejected_before_comparison(
    live_service_name: object,
    restore_service_name: object,
) -> None:
    """Namespace substitutes and bytes are not libpq service names."""
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ) as raised:
        verify_postgres_restore_target_isolation(
            live_service_name=live_service_name,  # type: ignore[arg-type]
            restore_service_name=restore_service_name,  # type: ignore[arg-type]
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=_identity(RESTORE_CLUSTER),
        )
    assert "secret" not in str(raised.value)


def test_cluster_identity_subclasses_and_substitutes_are_rejected() -> None:
    """Exact built-in identity records are the only accepted cluster evidence."""
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ):
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name="batch-restore-isolated",
            live_target_identity=_HostileClusterIdentity(
                system_identifier=LIVE_CLUSTER
            ),
            restore_target_identity=_identity(RESTORE_CLUSTER),
        )
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ):
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name="batch-restore-isolated",
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=SimpleNamespace(  # type: ignore[arg-type]
                system_identifier=RESTORE_CLUSTER
            ),
        )


@pytest.mark.parametrize(
    "system_identifier",
    [0, -1, True, "7438291055661123456", None, 1 << 64],
)
def test_invalid_system_identifiers_fail_closed(system_identifier: object) -> None:
    """Booleans, zero, negatives, and text are not PostgreSQL cluster identifiers."""
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ) as raised:
        PostgresRestoreTargetIdentity(system_identifier=system_identifier)  # type: ignore[arg-type]
    assert "secret" not in str(raised.value)
    assert "7438291055661123456" not in str(raised.value)


def test_tampered_cluster_identity_fails_closed_before_comparison() -> None:
    """A forged identity record cannot skip the bounded identifier grammar."""
    forged = object.__new__(PostgresRestoreTargetIdentity)
    object.__setattr__(forged, "system_identifier", 0)
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ) as raised:
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name="batch-restore-isolated",
            live_target_identity=forged,
            restore_target_identity=_identity(RESTORE_CLUSTER),
        )
    assert "secret" not in str(raised.value)


def test_deleted_cluster_identity_slot_fails_closed_before_comparison() -> None:
    """A removed caller-owned identifier remains a package validation failure."""
    damaged = _identity(RESTORE_CLUSTER)
    object.__delattr__(damaged, "system_identifier")

    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ) as raised:
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name="batch-restore-isolated",
            live_target_identity=_identity(LIVE_CLUSTER),
            restore_target_identity=damaged,
        )
    assert "secret" not in str(raised.value)
    assert str(RESTORE_CLUSTER) not in str(raised.value)


def test_verifier_does_not_accept_dsn_tenant_or_credential_arguments() -> None:
    """Callers cannot inject a DSN, tenant scope, or credential as target identity."""
    parameters = inspect.signature(verify_postgres_restore_target_isolation).parameters

    assert tuple(parameters) == (
        "live_service_name",
        "restore_service_name",
        "live_target_identity",
        "restore_target_identity",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters.values()
    )
    verify_postgres_restore_target_isolation(
        live_service_name="batch-prod",
        restore_service_name="batch-restore-isolated",
        live_target_identity=_identity(LIVE_CLUSTER),
        restore_target_identity=_identity(RESTORE_CLUSTER),
    )
