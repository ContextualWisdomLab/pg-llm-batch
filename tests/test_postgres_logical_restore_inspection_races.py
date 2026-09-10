# SPDX-License-Identifier: Apache-2.0
"""Regress fail-closed races between logical-restore snapshot and archive inspection."""

from __future__ import annotations

import os
import stat

import pytest

import pg_llm_batch.postgres_logical_restore as logical_restore
from pg_llm_batch.postgres_logical_restore import (
    PostgresLogicalRestoreError,
    restore_postgres_logical_backup,
)


def _open_private_archive(tmp_path, payload: bytes = b"PGDMP-inspection-race") -> int:
    """Create one private readable archive descriptor positioned at byte zero."""
    descriptor = os.open(
        tmp_path / "inspection-race.dump",
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    os.write(descriptor, payload)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor


def _restore(descriptor: int) -> None:
    """Invoke the trusted logical-restore boundary with fixed non-secret inputs."""
    restore_postgres_logical_backup(
        "isolated_restore",
        descriptor,
        source_superusers_trusted=True,
        pg_restore_executable="/usr/bin/pg_restore",
    )


def _forbid_subprocess(*_args, **_kwargs):
    """Fail if archive inspection reaches child execution."""
    pytest.fail("pg_restore must not run after archive inspection loses authority")


def test_restore_normalizes_snapshot_archive_stat_failure(tmp_path, monkeypatch):
    """Fail closed if the snapshotted caller authority cannot be statted."""
    descriptor = _open_private_archive(tmp_path)

    def fail_first_fstat(_target_descriptor):
        raise OSError("secret snapshot archive stat detail")

    monkeypatch.setattr(logical_restore.os, "fstat", fail_first_fstat)
    monkeypatch.setattr(logical_restore.subprocess, "run", _forbid_subprocess)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive could not be inspected$",
        ) as caught:
            _restore(descriptor)
        assert "secret" not in str(caught.value)
    finally:
        os.close(descriptor)


def test_restore_normalizes_independent_archive_stat_failure(tmp_path, monkeypatch):
    """Fail closed if the independently reopened archive cannot be statted."""
    descriptor = _open_private_archive(tmp_path)
    real_fstat = os.fstat
    fstat_calls = 0

    def fail_second_fstat(target_descriptor):
        nonlocal fstat_calls
        fstat_calls += 1
        if fstat_calls == 2:
            raise OSError("secret independent archive stat detail")
        return real_fstat(target_descriptor)

    monkeypatch.setattr(logical_restore.os, "fstat", fail_second_fstat)
    monkeypatch.setattr(logical_restore.subprocess, "run", _forbid_subprocess)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive could not be inspected$",
        ) as caught:
            _restore(descriptor)
        assert "secret" not in str(caught.value)
        assert fstat_calls == 2
    finally:
        os.close(descriptor)


def test_restore_rejects_independent_archive_type_change(tmp_path, monkeypatch):
    """Reject a reopened descriptor that ceases to identify a regular file."""
    descriptor = _open_private_archive(tmp_path)
    real_fstat = os.fstat
    fstat_calls = 0

    def change_second_fstat_type(target_descriptor):
        nonlocal fstat_calls
        fstat_calls += 1
        status = real_fstat(target_descriptor)
        if fstat_calls == 2:
            fields = list(status)
            fields[0] = stat.S_IFIFO | 0o600
            return os.stat_result(fields)
        return status

    monkeypatch.setattr(logical_restore.os, "fstat", change_second_fstat_type)
    monkeypatch.setattr(logical_restore.subprocess, "run", _forbid_subprocess)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must be a private regular file$",
        ):
            _restore(descriptor)
        assert fstat_calls == 2
    finally:
        os.close(descriptor)


def test_restore_normalizes_independent_archive_seek_failure(tmp_path, monkeypatch):
    """Fail closed if offset inspection fails only after the archive is reopened."""
    descriptor = _open_private_archive(tmp_path)
    real_lseek = os.lseek
    lseek_calls = 0

    def fail_second_lseek(target_descriptor, offset, whence):
        nonlocal lseek_calls
        lseek_calls += 1
        if lseek_calls == 2:
            raise OSError("secret independent archive seek detail")
        return real_lseek(target_descriptor, offset, whence)

    monkeypatch.setattr(logical_restore.os, "lseek", fail_second_lseek)
    monkeypatch.setattr(logical_restore.subprocess, "run", _forbid_subprocess)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive could not be inspected$",
        ) as caught:
            _restore(descriptor)
        assert "secret" not in str(caught.value)
        assert lseek_calls == 2
    finally:
        os.close(descriptor)


def test_restore_rejects_independent_archive_nonzero_offset(tmp_path, monkeypatch):
    """Reject a reopened archive whose independently observed offset is not zero."""
    descriptor = _open_private_archive(tmp_path)
    real_lseek = os.lseek
    lseek_calls = 0

    def change_second_lseek_offset(target_descriptor, offset, whence):
        nonlocal lseek_calls
        lseek_calls += 1
        if lseek_calls == 2:
            return 1
        return real_lseek(target_descriptor, offset, whence)

    monkeypatch.setattr(logical_restore.os, "lseek", change_second_lseek_offset)
    monkeypatch.setattr(logical_restore.subprocess, "run", _forbid_subprocess)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must start at offset zero$",
        ):
            _restore(descriptor)
        assert lseek_calls == 2
    finally:
        os.close(descriptor)
