# SPDX-License-Identifier: Apache-2.0
"""Regress caller descriptor authority races during PostgreSQL logical restore."""

from __future__ import annotations

import os
import subprocess

import pytest

import pg_llm_batch.postgres_logical_restore as logical_restore
from pg_llm_batch.postgres_logical_restore import (
    PostgresLogicalRestoreError,
    PostgresLogicalRestoreResult,
    restore_postgres_logical_backup,
)


@pytest.fixture(autouse=True)
def _stub_retained_executable_for_mocked_child(monkeypatch):
    """Keep mocked child tests independent of host PostgreSQL client packages."""
    real_open = os.open

    def open_inert_descriptor(_pg_restore_executable):
        return real_open(os.devnull, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))

    monkeypatch.setattr(
        logical_restore,
        "_open_retained_pg_restore_executable",
        open_inert_descriptor,
    )


def _open_private_archive(tmp_path, name: str, payload: bytes) -> int:
    """Create one private regular archive descriptor positioned at byte zero."""
    descriptor = os.open(
        tmp_path / name,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    os.write(descriptor, payload)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor


def test_restore_retains_inspected_archive_when_caller_replaces_descriptor(
    tmp_path, monkeypatch
):
    """Keep child authority on inspected bytes across caller-side ``dup2`` replacement."""
    original_payload = b"PGDMP-original"
    replacement_payload = b"PGDMP-replaced"
    caller_descriptor = _open_private_archive(
        tmp_path,
        "original.dump",
        original_payload,
    )
    replacement_descriptor = _open_private_archive(
        tmp_path,
        "replacement.dump",
        replacement_payload,
    )
    consumed_payloads: list[bytes] = []

    def replace_caller_descriptor_then_run(argv, **kwargs):
        os.dup2(replacement_descriptor, caller_descriptor)
        child_descriptor = kwargs["stdin"]
        os.lseek(child_descriptor, 0, os.SEEK_SET)
        consumed_payloads.append(os.read(child_descriptor, len(original_payload)))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        replace_caller_descriptor_then_run,
    )
    try:
        result = restore_postgres_logical_backup(
            "isolated_restore",
            caller_descriptor,
            source_superusers_trusted=True,
            pg_restore_executable="/usr/bin/pg_restore",
        )
        assert result == PostgresLogicalRestoreResult(size_bytes=len(original_payload))
        assert consumed_payloads == [original_payload]
    finally:
        os.close(caller_descriptor)
        os.close(replacement_descriptor)


def test_restore_isolates_child_offset_from_caller_seek(tmp_path, monkeypatch):
    """Keep caller seeks from moving the package-owned archive read position."""
    payload = b"PGDMP-offset-authority"
    caller_descriptor = _open_private_archive(tmp_path, "offset.dump", payload)
    observed_child_offsets: list[int] = []

    def seek_caller_then_run(argv, **kwargs):
        os.lseek(caller_descriptor, 5, os.SEEK_SET)
        observed_child_offsets.append(os.lseek(kwargs["stdin"], 0, os.SEEK_CUR))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_restore.subprocess, "run", seek_caller_then_run)
    try:
        result = restore_postgres_logical_backup(
            "isolated_restore",
            caller_descriptor,
            source_superusers_trusted=True,
            pg_restore_executable="/usr/bin/pg_restore",
        )
        assert result == PostgresLogicalRestoreResult(size_bytes=len(payload))
        assert observed_child_offsets == [0]
    finally:
        os.close(caller_descriptor)


def test_restore_rejects_write_only_archive_without_widening_authority(
    tmp_path, monkeypatch
):
    """Reject a write-only caller descriptor before any package reopen or child run."""
    archive_path = tmp_path / "write-only.dump"
    caller_descriptor = os.open(
        archive_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    os.write(caller_descriptor, b"PGDMP-write-only")
    os.lseek(caller_descriptor, 0, os.SEEK_SET)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive descriptor must be readable$",
        ):
            restore_postgres_logical_backup(
                "isolated_restore",
                caller_descriptor,
                source_superusers_trusted=True,
                pg_restore_executable="/usr/bin/pg_restore",
            )
    finally:
        os.close(caller_descriptor)


def test_restore_normalizes_independent_archive_reopen_failure(tmp_path, monkeypatch):
    """Fail closed without leaking platform detail when retained authority cannot reopen."""
    payload = b"PGDMP-reopen"
    caller_descriptor = _open_private_archive(tmp_path, "reopen.dump", payload)
    real_open = os.open

    def failing_reopen(path, flags, *args):
        if type(path) is str and path.startswith("/proc/self/fd/"):
            raise OSError("secret procfs detail")
        return real_open(path, flags, *args)

    monkeypatch.setattr(logical_restore.os, "open", failing_reopen)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive could not be isolated$",
        ) as caught:
            restore_postgres_logical_backup(
                "isolated_restore",
                caller_descriptor,
                source_superusers_trusted=True,
                pg_restore_executable="/usr/bin/pg_restore",
            )
        assert "secret" not in str(caught.value)
    finally:
        os.close(caller_descriptor)


def test_restore_does_not_mask_success_when_private_descriptor_close_fails(
    tmp_path, monkeypatch
):
    """Treat package-owned descriptor cleanup failure as bounded secondary evidence."""
    payload = b"PGDMP-close"
    caller_descriptor = _open_private_archive(tmp_path, "close.dump", payload)
    real_close = os.close
    retained_descriptor = None

    def consume_archive(argv, **kwargs):
        nonlocal retained_descriptor
        retained_descriptor = kwargs["stdin"]
        while os.read(retained_descriptor, 1024):
            pass
        return subprocess.CompletedProcess(argv, 0)

    def close_then_fail(target_descriptor):
        real_close(target_descriptor)
        if target_descriptor == retained_descriptor:
            raise OSError("secret retained descriptor close detail")

    monkeypatch.setattr(logical_restore.subprocess, "run", consume_archive)
    monkeypatch.setattr(logical_restore.os, "close", close_then_fail)
    try:
        result = restore_postgres_logical_backup(
            "isolated_restore",
            caller_descriptor,
            source_superusers_trusted=True,
            pg_restore_executable="/usr/bin/pg_restore",
        )
        assert result == PostgresLogicalRestoreResult(size_bytes=len(payload))
        assert retained_descriptor is not None
        assert retained_descriptor != caller_descriptor
    finally:
        real_close(caller_descriptor)
