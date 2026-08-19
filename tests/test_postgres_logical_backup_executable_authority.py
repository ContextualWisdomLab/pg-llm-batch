# SPDX-License-Identifier: Apache-2.0
"""Executable-authority regressions for PostgreSQL logical backup."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)


_TRUSTED_EXECUTABLE_BYTES = b"trusted pg_dump executable\n"
_INVALID_PARAMETERS = "^invalid PostgreSQL logical backup parameters$"


def _open_private_output(tmp_path: Path, name: str) -> tuple[Path, int]:
    """Create one owner-only empty logical-backup output capability."""
    output_path = tmp_path / name
    descriptor = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    return output_path, descriptor


def _write_pg_dump(tmp_path: Path, name: str = "pg_dump") -> Path:
    """Create one private executable token for authority-boundary tests."""
    executable = tmp_path / name
    executable.write_bytes(_TRUSTED_EXECUTABLE_BYTES)
    executable.chmod(0o500)
    return executable


def _with_owner(status: os.stat_result, user_id: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit owner identity."""
    fields = list(status)
    fields[4] = user_id
    return os.stat_result(fields)


def test_logical_backup_executes_retained_root_owned_pg_dump_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Late pathname replacement must not swap the pg_dump bytes executed."""
    _output_path, output_descriptor = _open_private_output(
        tmp_path,
        "retained-executable.dump",
    )
    executable = _write_pg_dump(tmp_path)
    real_fstat = os.fstat
    executable_status = os.stat(executable, follow_symlinks=False)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)

    def root_owned_executable(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) == executable_identity:
            return _with_owner(status, 0)
        return status

    def replace_path_then_run(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        retained_path = tmp_path / "retained-pg_dump"
        executable.rename(retained_path)
        executable.write_bytes(b"replacement executable bytes\n")
        executable.chmod(0o500)

        assert arguments[0].startswith("/proc/self/fd/")
        executable_descriptor = int(arguments[0].rsplit("/", 1)[-1])
        assert os.pread(
            executable_descriptor,
            len(_TRUSTED_EXECUTABLE_BYTES),
            0,
        ) == _TRUSTED_EXECUTABLE_BYTES
        pass_fds = kwargs["pass_fds"]
        assert type(pass_fds) is tuple
        assert executable_descriptor in pass_fds
        output = kwargs["stdout"]
        assert type(output) is int
        os.write(output, b"PGDMP\x01\x02\x03")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(os, "fstat", root_owned_executable)
    monkeypatch.setattr(subprocess, "run", replace_path_then_run)
    try:
        assert create_postgres_logical_backup(
            "safe_service",
            output_descriptor,
            pg_dump_executable=str(executable),
        ).size_bytes == 8
    finally:
        os.close(output_descriptor)


def test_logical_backup_rejects_effective_user_owned_pg_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service account must not retain chmod or rewrite authority to tool bytes."""
    _output_path, output_descriptor = _open_private_output(
        tmp_path,
        "service-owned-executable.dump",
    )
    executable = _write_pg_dump(tmp_path)
    real_fstat = os.fstat
    output_status = real_fstat(output_descriptor)
    executable_status = os.stat(executable, follow_symlinks=False)
    output_identity = (output_status.st_dev, output_status.st_ino)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)
    simulated_effective_user_id = 4242

    def service_owned_capabilities(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) in (output_identity, executable_identity):
            return _with_owner(status, simulated_effective_user_id)
        return status

    def forbidden_subprocess(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("service-owned pg_dump must fail before execution")

    monkeypatch.setattr(os, "geteuid", lambda: simulated_effective_user_id)
    monkeypatch.setattr(os, "fstat", service_owned_capabilities)
    monkeypatch.setattr(subprocess, "run", forbidden_subprocess)
    try:
        with pytest.raises(PostgresLogicalBackupError, match=_INVALID_PARAMETERS):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable=str(executable),
            )
    finally:
        os.close(output_descriptor)
