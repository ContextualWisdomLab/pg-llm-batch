# SPDX-License-Identifier: Apache-2.0
"""Fault-path regressions for retained PostgreSQL logical-backup executables."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Callable, NoReturn

import pytest

from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)


_INVALID_PARAMETERS = "^invalid PostgreSQL logical backup parameters$"


def _open_private_output(tmp_path: Path, name: str) -> int:
    """Create one owner-only empty logical-backup output descriptor."""
    return os.open(tmp_path / name, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)


def _write_pg_dump(tmp_path: Path) -> Path:
    """Create one executable token whose metadata tests may safely substitute."""
    executable = tmp_path / "pg_dump"
    executable.write_bytes(b"logical backup executable fixture\n")
    executable.chmod(0o500)
    return executable


def _with_owner(status: os.stat_result, user_id: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit owner identity."""
    fields = list(status)
    fields[4] = user_id
    return os.stat_result(fields)


def _with_mode(status: os.stat_result, mode: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit mode."""
    fields = list(status)
    fields[0] = mode
    return os.stat_result(fields)


def _forbidden_subprocess(*_args: object, **_kwargs: object) -> NoReturn:
    """Fail if an invalid retained executable reaches child execution."""
    raise AssertionError("invalid pg_dump authority must fail before execution")


@pytest.mark.parametrize("open_error", [OSError, ValueError])
def test_logical_backup_bounds_pg_dump_open_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    open_error: type[Exception],
) -> None:
    """Executable-open failures must stay content-free and precede provider execution."""
    output_descriptor = _open_private_output(tmp_path, "open-failure.dump")
    executable = _write_pg_dump(tmp_path)
    real_open = os.open

    def fail_executable_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fspath(path) == str(executable):
            raise open_error("private executable diagnostic")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", fail_executable_open)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresLogicalBackupError, match=_INVALID_PARAMETERS) as error:
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable=str(executable),
            )
        assert "private executable diagnostic" not in str(error.value)
    finally:
        os.close(output_descriptor)


def test_logical_backup_reports_missing_pg_dump_without_private_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing retained executable must expose only the package-authored category."""
    output_descriptor = _open_private_output(tmp_path, "missing-executable.dump")
    executable = _write_pg_dump(tmp_path)
    real_open = os.open

    def missing_executable_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fspath(path) == str(executable):
            raise FileNotFoundError("private missing-path diagnostic")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", missing_executable_open)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup executable unavailable$",
        ) as error:
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable=str(executable),
            )
        assert "private missing-path diagnostic" not in str(error.value)
    finally:
        os.close(output_descriptor)


@pytest.mark.parametrize("fstat_error", [AttributeError, OSError, ValueError])
def test_logical_backup_closes_retained_executable_when_metadata_inspection_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fstat_error: type[Exception],
) -> None:
    """Metadata inspection failure must close retained executable authority fail-closed."""
    output_descriptor = _open_private_output(tmp_path, "metadata-failure.dump")
    executable = _write_pg_dump(tmp_path)
    executable_status = os.stat(executable, follow_symlinks=False)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)
    real_fstat = os.fstat
    retained_descriptors: list[int] = []

    def fail_executable_fstat(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) == executable_identity:
            retained_descriptors.append(file_descriptor)
            raise fstat_error("private metadata diagnostic")
        return status

    monkeypatch.setattr(os, "fstat", fail_executable_fstat)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresLogicalBackupError, match=_INVALID_PARAMETERS) as error:
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable=str(executable),
            )
        assert "private metadata diagnostic" not in str(error.value)
        assert len(retained_descriptors) == 1
        with pytest.raises(OSError):
            real_fstat(retained_descriptors[0])
    finally:
        os.close(output_descriptor)


def _non_regular(status: os.stat_result) -> os.stat_result:
    return _with_mode(status, stat.S_IFDIR | 0o500)


def _group_writable(status: os.stat_result) -> os.stat_result:
    return _with_mode(status, status.st_mode | stat.S_IWGRP)


def _other_writable(status: os.stat_result) -> os.stat_result:
    return _with_mode(status, status.st_mode | stat.S_IWOTH)


def _non_executable(status: os.stat_result) -> os.stat_result:
    return _with_mode(status, status.st_mode & ~0o111)


@pytest.mark.parametrize(
    "mutate_status",
    [_non_regular, _group_writable, _other_writable, _non_executable],
    ids=["non-regular", "group-writable", "other-writable", "non-executable"],
)
def test_logical_backup_rejects_unsafe_root_owned_pg_dump_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate_status: Callable[[os.stat_result], os.stat_result],
) -> None:
    """Every unsafe executable metadata class must be rejected before child execution."""
    output_descriptor = _open_private_output(tmp_path, "unsafe-metadata.dump")
    executable = _write_pg_dump(tmp_path)
    executable_status = os.stat(executable, follow_symlinks=False)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)
    real_fstat = os.fstat
    retained_descriptors: list[int] = []

    def unsafe_root_owned_executable(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) == executable_identity:
            retained_descriptors.append(file_descriptor)
            return mutate_status(_with_owner(status, 0))
        return status

    monkeypatch.setattr(os, "fstat", unsafe_root_owned_executable)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresLogicalBackupError, match=_INVALID_PARAMETERS):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable=str(executable),
            )
        assert len(retained_descriptors) == 1
        with pytest.raises(OSError):
            real_fstat(retained_descriptors[0])
    finally:
        os.close(output_descriptor)
