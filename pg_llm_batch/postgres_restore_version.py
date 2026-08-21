# SPDX-License-Identifier: Apache-2.0
"""Verify PostgreSQL restore-target server major compatibility."""

from __future__ import annotations


_SERVER_VERSION_SQL = "SELECT pg_catalog.current_setting('server_version_num')"
_MIN_SUPPORTED_MAJOR = 10
_MAX_SUPPORTED_MAJOR = 99
_MIN_SERVER_VERSION_NUM = 100000
_MAX_SERVER_VERSION_NUM = 999999


class PostgresRestoreVersionError(ValueError):
    """Report a fail-closed restore-target server-version violation."""


def _plain_expected_major(value: object) -> bool:
    """Return whether a value is one exact supported PostgreSQL major integer."""
    return (
        type(value) is int
        and _MIN_SUPPORTED_MAJOR <= value <= _MAX_SUPPORTED_MAJOR
    )


def _parse_server_version_row(row: object) -> tuple[int, int]:
    """Parse one exact bounded ``server_version_num`` catalog result row."""
    if type(row) is not tuple or len(row) != 1:
        raise PostgresRestoreVersionError(
            "PostgreSQL restore version evidence is invalid"
        )
    raw_version = row[0]
    if (
        type(raw_version) is not str
        or not raw_version.isascii()
        or not raw_version.isdecimal()
    ):
        raise PostgresRestoreVersionError(
            "PostgreSQL restore version evidence is invalid"
        )
    server_version_num = int(raw_version)
    if not (
        _MIN_SERVER_VERSION_NUM
        <= server_version_num
        <= _MAX_SERVER_VERSION_NUM
    ):
        raise PostgresRestoreVersionError(
            "PostgreSQL restore version evidence is invalid"
        )
    observed_major = server_version_num // 10000
    if not _plain_expected_major(observed_major):
        raise PostgresRestoreVersionError(
            "PostgreSQL restore version evidence is invalid"
        )
    return server_version_num, observed_major


def verify_postgres_restore_server_major(
    connection: object,
    *,
    expected_postgres_major: int,
) -> int:
    """Verify a caller-owned restore target matches the recovery major version.

    The caller supplies an already-opened PostgreSQL connection and the major
    version bound by its recovery profile or backup evidence. The package issues
    one fixed catalog-qualified ``current_setting('server_version_num')`` query,
    accepts only one exact built-in tuple/string result, and fails closed when
    the observed major differs.

    The function does not open a connection, inspect a DSN, mutate the session,
    execute recovery, prove WAL compatibility, or claim restore success. The
    returned integer is the observed PostgreSQL ``server_version_num`` for the
    caller's immediate use; it is not a signed or independently durable receipt.
    """
    if not _plain_expected_major(expected_postgres_major):
        raise PostgresRestoreVersionError(
            "invalid PostgreSQL restore version inputs"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute(_SERVER_VERSION_SQL)
            row = cursor.fetchone()
    except Exception:
        raise PostgresRestoreVersionError(
            "PostgreSQL restore server version could not be inspected"
        ) from None

    server_version_num, observed_major = _parse_server_version_row(row)
    if observed_major != expected_postgres_major:
        raise PostgresRestoreVersionError(
            "PostgreSQL restore target major version does not match recovery profile"
        )
    return server_version_num
