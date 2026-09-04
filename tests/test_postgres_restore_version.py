# SPDX-License-Identifier: Apache-2.0
"""Server-version regressions for an isolated PostgreSQL restore target."""

from __future__ import annotations

import pytest

from pg_llm_batch.postgres_restore_version import (
    PostgresRestoreVersionError,
    verify_postgres_restore_server_major,
)


class _VersionCursor:
    """Return one caller-owned server-version row through a fixed SQL seam."""

    def __init__(self, row: object) -> None:
        self.row = row
        self.executed_sql: str | None = None

    def __enter__(self) -> _VersionCursor:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: object) -> None:
        if type(sql) is not str:
            raise AssertionError("version SQL must be an exact built-in string")
        self.executed_sql = sql

    def fetchone(self) -> object:
        return self.row


class _VersionConnection:
    """Expose one caller-owned connection without carrying a DSN."""

    def __init__(self, row: object) -> None:
        self.cursor_handle = _VersionCursor(row)

    def cursor(self) -> _VersionCursor:
        return self.cursor_handle


class _HostileVersion(str):
    """Refuse rendering if rejected version content reaches diagnostics."""

    def __str__(self) -> str:
        raise AssertionError("must not render hostile version text")


class _ExecuteFailureCursor(_VersionCursor):
    """Raise one credential-like lower-layer error during the fixed query."""

    def execute(self, sql: object) -> None:
        del sql
        raise RuntimeError("password=supersecret host=restore.internal")


class _ExecuteFailureConnection(_VersionConnection):
    """Expose the failing cursor through the caller-owned connection seam."""

    def cursor(self) -> _VersionCursor:
        return _ExecuteFailureCursor(("180004",))


def test_verify_restore_server_major_accepts_matching_postgres_18() -> None:
    connection = _VersionConnection(("180004",))

    observed = verify_postgres_restore_server_major(
        connection,
        expected_postgres_major=18,
    )

    assert observed == 180004
    assert connection.cursor_handle.executed_sql == (
        "SELECT pg_catalog.current_setting('server_version_num')"
    )


def test_verify_restore_server_major_rejects_wrong_major() -> None:
    connection = _VersionConnection(("170009",))

    with pytest.raises(
        PostgresRestoreVersionError,
        match="PostgreSQL restore target major version does not match recovery profile",
    ):
        verify_postgres_restore_server_major(
            connection,
            expected_postgres_major=18,
        )


@pytest.mark.parametrize(
    "expected_postgres_major",
    [True, 9, 100, "18"],
)
def test_verify_restore_server_major_rejects_invalid_expected_major(
    expected_postgres_major: object,
) -> None:
    connection = _VersionConnection(("180004",))

    with pytest.raises(
        PostgresRestoreVersionError,
        match="invalid PostgreSQL restore version inputs",
    ):
        verify_postgres_restore_server_major(
            connection,
            expected_postgres_major=expected_postgres_major,  # type: ignore[arg-type]
        )

    assert connection.cursor_handle.executed_sql is None


@pytest.mark.parametrize(
    "row",
    [
        None,
        ["180004"],
        (),
        ("180004", "extra"),
        (180004,),
        (_HostileVersion("180004"),),
        ("１８０００４",),
        (" 180004",),
        ("99999",),
        ("1000000",),
    ],
)
def test_verify_restore_server_major_rejects_malformed_server_version_row(
    row: object,
) -> None:
    connection = _VersionConnection(row)

    with pytest.raises(
        PostgresRestoreVersionError,
        match="PostgreSQL restore version evidence is invalid",
    ):
        verify_postgres_restore_server_major(
            connection,
            expected_postgres_major=18,
        )


def test_verify_restore_server_major_hides_lower_layer_diagnostics() -> None:
    connection = _ExecuteFailureConnection(("180004",))

    with pytest.raises(
        PostgresRestoreVersionError,
        match="PostgreSQL restore server version could not be inspected",
    ) as raised:
        verify_postgres_restore_server_major(
            connection,
            expected_postgres_major=18,
        )

    assert "supersecret" not in str(raised.value)
    assert "restore.internal" not in str(raised.value)
    assert raised.value.__cause__ is None
