# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for isolated restore-target service identity."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from pg_llm_batch.postgres_restore_target import (
    PostgresRestoreTargetError,
    verify_postgres_restore_target_isolation,
)


class _HostileServiceName(str):
    """Identify a caller-controlled libpq service-name subclass."""


def test_operator_can_separate_live_batch_from_isolated_restore_service() -> None:
    """A production pg_service name must stay distinct from the restore-drill name."""
    verify_postgres_restore_target_isolation(
        live_service_name="batch-prod",
        restore_service_name="batch-restore-isolated",
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
        )
    assert "batch-prod" not in str(raised.value)
    assert "postgresql://" not in str(raised.value)
    assert "secret" not in str(raised.value)


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
        )
    with pytest.raises(
        PostgresRestoreTargetError,
        match="^invalid PostgreSQL restore target isolation inputs$",
    ):
        verify_postgres_restore_target_isolation(
            live_service_name="batch-prod",
            restore_service_name=_HostileServiceName("batch-restore-isolated"),
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
        )
    assert "secret" not in str(raised.value)


def test_verifier_does_not_accept_dsn_tenant_or_credential_arguments() -> None:
    """Callers cannot inject a DSN, tenant scope, or credential as target identity."""
    names = verify_postgres_restore_target_isolation.__code__.co_varnames
    parameters = inspect.signature(verify_postgres_restore_target_isolation).parameters

    assert "dsn" not in names
    assert "conninfo" not in names
    assert "password" not in names
    assert "tenant_scope" not in names
    assert "backup_artifact_path" not in names
    assert "live_service_name" in parameters
    assert "restore_service_name" in parameters
    verify_postgres_restore_target_isolation(
        live_service_name="batch-prod",
        restore_service_name="batch-restore-isolated",
    )
