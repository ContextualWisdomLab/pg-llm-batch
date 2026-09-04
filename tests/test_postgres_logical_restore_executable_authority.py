# SPDX-License-Identifier: Apache-2.0
"""Regressions for retained pg_restore executable authority."""

from __future__ import annotations

import stat
import subprocess
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_logical_restore as logical_restore
from pg_llm_batch.postgres_logical_restore import PostgresLogicalRestoreError


def test_pg_restore_execution_uses_retained_inode_after_path_replacement(monkeypatch):
    """Execute through retained descriptor authority, not the mutable caller path."""
    executable_descriptor = 41
    opened = []
    closed = []

    def fake_open(path, flags):
        opened.append((path, flags))
        return executable_descriptor

    def fake_fstat(descriptor):
        assert descriptor == executable_descriptor
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)

    def fake_close(descriptor):
        closed.append(descriptor)

    def fake_run(argv, **kwargs):
        # Model replacement of the caller-controlled pathname after retention.
        # Child execution must remain pinned to the already-open descriptor.
        assert opened
        assert argv[0] == "/opt/postgresql/18/bin/pg_restore"
        assert kwargs["executable"] == f"/proc/self/fd/{executable_descriptor}"
        assert kwargs["pass_fds"] == (executable_descriptor,)
        assert kwargs["close_fds"] is True
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_restore.os, "open", fake_open)
    monkeypatch.setattr(logical_restore.os, "fstat", fake_fstat)
    monkeypatch.setattr(logical_restore.os, "close", fake_close)
    monkeypatch.setattr(logical_restore.subprocess, "run", fake_run)

    logical_restore._run_pg_restore(
        service_name="isolated_restore",
        input_descriptor=7,
        pg_restore_executable="/opt/postgresql/18/bin/pg_restore",
        timeout_seconds=30,
        connect_timeout_seconds=5,
    )

    assert opened[0][0] == "/opt/postgresql/18/bin/pg_restore"
    flags = opened[0][1]
    assert flags & getattr(logical_restore.os, "O_CLOEXEC", 0) == getattr(
        logical_restore.os, "O_CLOEXEC", 0
    )
    assert flags & getattr(logical_restore.os, "O_NOFOLLOW", 0) == getattr(
        logical_restore.os, "O_NOFOLLOW", 0
    )
    assert flags & getattr(logical_restore.os, "O_NONBLOCK", 0) == getattr(
        logical_restore.os, "O_NONBLOCK", 0
    )
    assert closed == [executable_descriptor]


@pytest.mark.parametrize(
    "failure",
    [
        OSError("secret open detail"),
        ValueError("secret open value"),
        OverflowError("secret open overflow"),
    ],
)
def test_pg_restore_executable_open_failures_are_bounded(monkeypatch, failure):
    """Normalize platform-specific executable-open failures without leaking detail."""

    def fail_open(_path, _flags):
        raise failure

    monkeypatch.setattr(logical_restore.os, "open", fail_open)
    with pytest.raises(
        PostgresLogicalRestoreError,
        match="^PostgreSQL logical restore executable unavailable$",
    ) as caught:
        logical_restore._open_retained_pg_restore_executable("/usr/bin/pg_restore")
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [OSError("secret stat detail"), ValueError("secret stat value")],
)
def test_pg_restore_executable_stat_failures_close_authority(
    monkeypatch, failure
):
    """Close retained authority when executable metadata cannot be inspected."""
    executable_descriptor = 41
    closed = []

    monkeypatch.setattr(logical_restore.os, "open", lambda _path, _flags: executable_descriptor)

    def fail_fstat(_descriptor):
        raise failure

    monkeypatch.setattr(logical_restore.os, "fstat", fail_fstat)
    monkeypatch.setattr(logical_restore.os, "close", closed.append)

    with pytest.raises(
        PostgresLogicalRestoreError,
        match="^PostgreSQL logical restore executable could not be inspected$",
    ) as caught:
        logical_restore._open_retained_pg_restore_executable("/usr/bin/pg_restore")
    assert "secret" not in str(caught.value)
    assert closed == [executable_descriptor]


@pytest.mark.parametrize(
    ("mode", "uid"),
    [
        (stat.S_IFIFO | 0o755, 0),
        (stat.S_IFREG | 0o755, 1000),
        (stat.S_IFREG | 0o644, 0),
        (stat.S_IFREG | 0o775, 0),
        (stat.S_IFREG | 0o757, 0),
        (stat.S_IFREG | stat.S_ISUID | 0o755, 0),
        (stat.S_IFREG | stat.S_ISGID | 0o755, 0),
    ],
)
def test_pg_restore_executable_rejects_unsafe_inode_authority(monkeypatch, mode, uid):
    """Reject non-regular, non-root, non-executable, writable, or set-id authority."""
    executable_descriptor = 41
    closed = []

    monkeypatch.setattr(logical_restore.os, "open", lambda _path, _flags: executable_descriptor)
    monkeypatch.setattr(
        logical_restore.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(st_mode=mode, st_uid=uid),
    )
    monkeypatch.setattr(logical_restore.os, "close", closed.append)

    with pytest.raises(
        PostgresLogicalRestoreError,
        match="^PostgreSQL logical restore executable is unsafe$",
    ):
        logical_restore._open_retained_pg_restore_executable("/usr/bin/pg_restore")
    assert closed == [executable_descriptor]


@pytest.mark.parametrize(
    "failure",
    [OSError("secret close detail"), ValueError("secret close value")],
)
def test_pg_restore_executable_close_failures_are_secondary(monkeypatch, failure):
    """Keep descriptor-cleanup failures from masking primary execution evidence."""

    def fail_close(_descriptor):
        raise failure

    monkeypatch.setattr(logical_restore.os, "close", fail_close)
    logical_restore._close_retained_executable_descriptor(41)
