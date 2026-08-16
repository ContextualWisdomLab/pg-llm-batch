# SPDX-License-Identifier: Apache-2.0
"""Prove a restore libpq service name is distinct from the live service."""

from __future__ import annotations

import re


_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class PostgresRestoreTargetError(ValueError):
    """Report a fail-closed isolated restore-target identity violation."""


def _plain_service_name(value: object) -> bool:
    """Return whether a value is an exact built-in libpq service name."""
    return type(value) is str and _SERVICE_NAME_RE.fullmatch(value) is not None


def verify_postgres_restore_target_isolation(
    *,
    live_service_name: str,
    restore_service_name: str,
) -> None:
    """Fail closed unless the restore service is a distinct reviewed identity.

    Operators pass the live ``pg_service.conf`` name and the isolated
    restore-drill name. Both must be exact built-in strings that match the
    same libpq service-name grammar used by the logical dump and restore
    executors. The names must differ. The function does not accept a DSN,
    password, ``tenant_scope``, host, port, or backup-byte argument, and it
    does not execute ``pg_dump`` or ``pg_restore``.
    """
    if not _plain_service_name(live_service_name) or not _plain_service_name(
        restore_service_name
    ):
        raise PostgresRestoreTargetError(
            "invalid PostgreSQL restore target isolation inputs"
        )
    if live_service_name == restore_service_name:
        raise PostgresRestoreTargetError(
            "PostgreSQL restore target is not isolated from the live service"
        )
