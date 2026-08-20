# SPDX-License-Identifier: Apache-2.0
"""Regressions for retained pg_restore executable authority."""

from __future__ import annotations

import stat
import subprocess
from types import SimpleNamespace

import pg_llm_batch.postgres_logical_restore as logical_restore


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
    assert closed == [executable_descriptor]
