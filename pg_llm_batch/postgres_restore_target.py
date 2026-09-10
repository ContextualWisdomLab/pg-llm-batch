# SPDX-License-Identifier: Apache-2.0
"""Prove a restore target is a distinct libpq name and cluster identity."""

from __future__ import annotations

import re
from dataclasses import dataclass


_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_SYSTEM_IDENTIFIER = (1 << 64) - 1


class PostgresRestoreTargetError(ValueError):
    """Report a fail-closed isolated restore-target identity violation."""


@dataclass(frozen=True, slots=True)
class PostgresRestoreTargetIdentity:
    """Represent caller-owned PostgreSQL cluster identity for one target.

    Operators obtain ``system_identifier`` from ``pg_control_system()`` on a
    connection they already opened. The package does not open a connection,
    read ``pg_service.conf``, or accept a DSN.
    """

    system_identifier: int

    def __post_init__(self) -> None:
        """Fail closed when the cluster identifier is not a bounded integer."""
        if not _plain_system_identifier(self.system_identifier):
            raise PostgresRestoreTargetError(
                "invalid PostgreSQL restore target isolation inputs"
            )


def _plain_service_name(value: object) -> bool:
    """Return whether a value is an exact built-in libpq service name."""
    return type(value) is str and _SERVICE_NAME_RE.fullmatch(value) is not None


def _plain_system_identifier(value: object) -> bool:
    """Return whether a value is an exact positive PostgreSQL system identifier."""
    return type(value) is int and 1 <= value <= _MAX_SYSTEM_IDENTIFIER


def verify_postgres_restore_target_isolation(
    *,
    live_service_name: str,
    restore_service_name: str,
    live_target_identity: PostgresRestoreTargetIdentity,
    restore_target_identity: PostgresRestoreTargetIdentity,
) -> None:
    """Fail closed unless the restore name and cluster identity both differ.

    Operators pass the live ``pg_service.conf`` name, the isolated
    restore-drill name, and caller-owned cluster identities collected from
    connections they already opened. Both names must be exact built-in
    strings that match the same libpq service-name grammar used by the
    logical dump and restore executors. Both identities must be exact
    ``PostgresRestoreTargetIdentity`` values whose ``system_identifier``
    values differ. The verifier snapshots those caller-owned identifiers once
    and makes the isolation decision only from the validated local snapshot.
    Distinct names alone are not isolation: two service sections or DNS aliases
    can resolve to the same cluster. The function does not accept a DSN,
    password, ``tenant_scope``, host, port, or backup-byte argument, and it
    does not execute ``pg_dump`` or ``pg_restore``.
    """
    if not _plain_service_name(live_service_name) or not _plain_service_name(
        restore_service_name
    ):
        raise PostgresRestoreTargetError(
            "invalid PostgreSQL restore target isolation inputs"
        )
    if (
        type(live_target_identity) is not PostgresRestoreTargetIdentity
        or type(restore_target_identity) is not PostgresRestoreTargetIdentity
    ):
        raise PostgresRestoreTargetError(
            "invalid PostgreSQL restore target isolation inputs"
        )
    try:
        live_system_identifier = live_target_identity.system_identifier
        restore_system_identifier = restore_target_identity.system_identifier
    except AttributeError:
        raise PostgresRestoreTargetError(
            "invalid PostgreSQL restore target isolation inputs"
        ) from None
    if not _plain_system_identifier(
        live_system_identifier
    ) or not _plain_system_identifier(restore_system_identifier):
        raise PostgresRestoreTargetError(
            "invalid PostgreSQL restore target isolation inputs"
        )
    if live_service_name == restore_service_name:
        raise PostgresRestoreTargetError(
            "PostgreSQL restore target is not isolated from the live service"
        )
    if live_system_identifier == restore_system_identifier:
        raise PostgresRestoreTargetError(
            "PostgreSQL restore target is not isolated from the live service"
        )
