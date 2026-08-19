# SPDX-License-Identifier: Apache-2.0
"""Regression tests for logical-backup output-descriptor identity."""

from __future__ import annotations

import os
import subprocess

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    PostgresLogicalBackupResult,
    create_postgres_logical_backup,
)


def test_logical_backup_child_uses_snapshotted_output_authority(
    tmp_path, monkeypatch
):
    """Keep pg_dump bound to the inspected file after caller-fd substitution."""
    original_path = tmp_path / "snapshotted.dump"
    replacement_path = tmp_path / "replacement.dump"
    descriptor = os.open(original_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    replacement_descriptor = os.open(
        replacement_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
    )

    def substitute_caller_descriptor(argv, **kwargs):
        assert kwargs["stdout"] != descriptor
        os.dup2(replacement_descriptor, descriptor)
        os.write(kwargs["stdout"], b"PGDMP-safe")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.subprocess, "run", substitute_caller_descriptor)
    try:
        assert create_postgres_logical_backup(
            "safe_service",
            descriptor,
            pg_dump_executable="/usr/bin/pg_dump",
        ) == PostgresLogicalBackupResult(size_bytes=10)

        with original_path.open("rb") as original_file:
            assert original_file.read() == b"PGDMP-safe"
        with replacement_path.open("rb") as replacement_file:
            assert replacement_file.read() == b""
    finally:
        os.close(replacement_descriptor)
        os.close(descriptor)


def test_logical_backup_child_offset_is_independent_from_caller_descriptor(
    tmp_path, monkeypatch
):
    """Keep caller seek authority from moving the pg_dump output position."""
    original_path = tmp_path / "independent-offset.dump"
    descriptor = os.open(original_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)

    def shift_caller_offset_then_write(argv, **kwargs):
        assert kwargs["stdout"] != descriptor
        os.lseek(descriptor, 4096, os.SEEK_SET)
        assert os.lseek(kwargs["stdout"], 0, os.SEEK_CUR) == 0
        os.write(kwargs["stdout"], b"PGDMP-safe")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.subprocess, "run", shift_caller_offset_then_write)
    try:
        assert create_postgres_logical_backup(
            "safe_service",
            descriptor,
            pg_dump_executable="/usr/bin/pg_dump",
        ) == PostgresLogicalBackupResult(size_bytes=10)
        with original_path.open("rb") as original_file:
            assert original_file.read() == b"PGDMP-safe"
    finally:
        os.close(descriptor)


def test_logical_backup_failure_cleans_snapshotted_output_after_caller_substitution(
    tmp_path, monkeypatch
):
    """Clean only original output when pg_dump fails after caller-fd substitution."""
    original_path = tmp_path / "original-failure.dump"
    replacement_path = tmp_path / "replacement-failure.dump"
    descriptor = os.open(original_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    replacement_descriptor = os.open(
        replacement_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
    )

    def substitute_then_fail(argv, **kwargs):
        assert kwargs["stdout"] != descriptor
        os.dup2(replacement_descriptor, descriptor)
        os.write(kwargs["stdout"], b"partial-sensitive-backup")
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(logical_backup.subprocess, "run", substitute_then_fail)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match=r"^PostgreSQL logical backup command failed$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )

        with original_path.open("rb") as original_file:
            assert original_file.read() == b""
        with replacement_path.open("rb") as replacement_file:
            assert replacement_file.read() == b""
    finally:
        os.close(replacement_descriptor)
        os.close(descriptor)


def test_logical_backup_normalizes_cleanup_descriptor_dup_failure(
    tmp_path, monkeypatch
):
    """Fail with bounded evidence if output authority cannot be snapshotted."""
    original_path = tmp_path / "dup-failure.dump"
    descriptor = os.open(original_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    subprocess_called = False

    def fail_dup(_descriptor):
        raise OSError("secret duplicate failure")

    def forbidden_run(*_args, **_kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(logical_backup.os, "dup", fail_dup)
    monkeypatch.setattr(logical_backup.subprocess, "run", forbidden_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match=r"^PostgreSQL logical backup output could not be retained$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "secret" not in str(caught.value)
        assert subprocess_called is False
    finally:
        os.close(descriptor)


def test_logical_backup_normalizes_oversized_output_descriptor(monkeypatch):
    """Bound platform integer-conversion failure before any child process runs."""
    subprocess_called = False

    def forbidden_run(*_args, **_kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(logical_backup.subprocess, "run", forbidden_run)
    with pytest.raises(
        PostgresLogicalBackupError,
        match=r"^PostgreSQL logical backup output could not be retained$",
    ):
        create_postgres_logical_backup(
            "safe_service",
            1 << 1000,
            pg_dump_executable="/usr/bin/pg_dump",
        )
    assert subprocess_called is False


def test_logical_backup_cleanup_close_failure_preserves_success(
    tmp_path, monkeypatch
):
    """Do not replace valid backup evidence with an authority-close diagnostic."""
    original_path = tmp_path / "close-failure.dump"
    descriptor = os.open(original_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    real_close = os.close
    leaked_cleanup_descriptors: list[int] = []

    def write_successfully(argv, **kwargs):
        os.write(kwargs["stdout"], b"PGDMP-safe")
        return subprocess.CompletedProcess(argv, 0)

    def fail_cleanup_close(target_descriptor):
        if target_descriptor == descriptor:
            return real_close(target_descriptor)
        leaked_cleanup_descriptors.append(target_descriptor)
        raise OSError("secret cleanup close failure")

    monkeypatch.setattr(logical_backup.subprocess, "run", write_successfully)
    monkeypatch.setattr(logical_backup.os, "close", fail_cleanup_close)
    try:
        assert create_postgres_logical_backup(
            "safe_service",
            descriptor,
            pg_dump_executable="/usr/bin/pg_dump",
        ) == PostgresLogicalBackupResult(size_bytes=10)
        assert len(leaked_cleanup_descriptors) == 1
    finally:
        monkeypatch.setattr(logical_backup.os, "close", real_close)
        for cleanup_descriptor in leaked_cleanup_descriptors:
            real_close(cleanup_descriptor)
        real_close(descriptor)
