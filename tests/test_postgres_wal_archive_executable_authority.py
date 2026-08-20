# SPDX-License-Identifier: Apache-2.0
"""Executable-authority regressions for bounded PostgreSQL WAL reception."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_wal_archive as wal_archive
from pg_llm_batch.postgres_wal_archive import (
    PostgresWalArchiveError,
    PostgresWalArchiveResult,
    receive_postgres_wal_archive,
)


_TRUSTED_EXECUTABLE_BYTES = b"trusted pg_receivewal bytes\n"
_INVALID_PARAMETERS = "^invalid PostgreSQL WAL archive parameters$"


@pytest.fixture(autouse=True)
def _accept_bounded_filesystem_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolate executable-authority tests from host mount topology."""

    def accept_bounded_filesystem(
        _archive_directory_descriptor: int,
        maximum_archive_bytes: int,
    ) -> int:
        return maximum_archive_bytes

    monkeypatch.setattr(
        wal_archive,
        "_inspect_archive_filesystem_budget",
        accept_bounded_filesystem,
    )


def _open_private_archive(tmp_path: Path, name: str) -> int:
    """Create and open one owner-only empty WAL archive directory."""
    archive_path = tmp_path / name
    archive_path.mkdir(mode=0o700)
    return os.open(archive_path, os.O_RDONLY | os.O_DIRECTORY)


def _write_receivewal(tmp_path: Path, *, name: str = "pg_receivewal") -> Path:
    """Create one temporary executable token for retained-inode tests."""
    executable = tmp_path / name
    executable.write_bytes(_TRUSTED_EXECUTABLE_BYTES)
    executable.chmod(0o500)
    return executable


def _with_metadata(
    status: os.stat_result,
    *,
    user_id: int | None = None,
    mode: int | None = None,
) -> os.stat_result:
    """Return equivalent stat metadata with selected authority fields replaced."""
    fields = list(status)
    if mode is not None:
        fields[0] = mode
    if user_id is not None:
        fields[4] = user_id
    return os.stat_result(fields)


def test_receiver_executes_the_retained_receivewal_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pathname swap after validation must not replace child executable bytes."""
    archive_descriptor = _open_private_archive(tmp_path, "path-race-archive")
    executable_path = _write_receivewal(tmp_path)
    real_fstat = os.fstat
    executable_status = executable_path.stat()
    executable_identity = (executable_status.st_dev, executable_status.st_ino)

    def root_owned_executable(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == executable_identity:
            return _with_metadata(observed, user_id=0)
        return observed

    def replace_path_then_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        assert arguments[0] == str(executable_path)
        retained_path = tmp_path / "retained-pg_receivewal"
        executable_path.rename(retained_path)
        executable_path.write_bytes(b"attacker replacement bytes\n")
        executable_path.chmod(0o500)
        executable_authority = kwargs["executable"]
        assert isinstance(executable_authority, str)
        assert executable_authority.startswith("/proc/self/fd/")
        executable_descriptor = int(executable_authority.rsplit("/", 1)[-1])
        assert executable_descriptor in kwargs["pass_fds"]
        assert os.pread(
            executable_descriptor,
            len(_TRUSTED_EXECUTABLE_BYTES),
            0,
        ) == _TRUSTED_EXECUTABLE_BYTES
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(os, "fstat", root_owned_executable)
    monkeypatch.setattr(subprocess, "run", replace_path_then_run)
    try:
        assert receive_postgres_wal_archive(
            "physical_replication_source",
            "pg_llm_batch_archive",
            "16/B374D848",
            archive_descriptor,
            pg_receivewal_executable=str(executable_path),
        ) == PostgresWalArchiveResult(end_lsn="16/B374D848")
    finally:
        os.close(archive_descriptor)


def test_receiver_rejects_effective_user_owned_receivewal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-root service owner must not retain rewrite authority to tool bytes."""
    archive_descriptor = _open_private_archive(tmp_path, "service-owner-archive")
    executable_path = _write_receivewal(tmp_path)
    real_fstat = os.fstat
    archive_status = real_fstat(archive_descriptor)
    executable_status = executable_path.stat()
    archive_identity = (archive_status.st_dev, archive_status.st_ino)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)
    simulated_effective_user_id = 4242

    def service_owned_authority(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        identity = (observed.st_dev, observed.st_ino)
        if identity in (archive_identity, executable_identity):
            return _with_metadata(observed, user_id=simulated_effective_user_id)
        return observed

    def forbidden_run(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("service-owned pg_receivewal must fail before execution")

    monkeypatch.setattr(os, "geteuid", lambda: simulated_effective_user_id)
    monkeypatch.setattr(os, "fstat", service_owned_authority)
    monkeypatch.setattr(subprocess, "run", forbidden_run)
    try:
        with pytest.raises(PostgresWalArchiveError, match=_INVALID_PARAMETERS):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                archive_descriptor,
                pg_receivewal_executable=str(executable_path),
            )
    finally:
        os.close(archive_descriptor)


@pytest.mark.parametrize("set_id_bit", [stat.S_ISUID, stat.S_ISGID])
def test_receiver_rejects_set_id_receivewal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    set_id_bit: int,
) -> None:
    """Retained tool authority must not cross an unreviewed privilege transition."""
    archive_descriptor = _open_private_archive(
        tmp_path,
        f"set-id-archive-{set_id_bit:o}",
    )
    executable_path = _write_receivewal(tmp_path)
    real_fstat = os.fstat
    executable_status = executable_path.stat()
    executable_identity = (executable_status.st_dev, executable_status.st_ino)

    def unsafe_root_executable(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == executable_identity:
            return _with_metadata(
                observed,
                user_id=0,
                mode=observed.st_mode | set_id_bit,
            )
        return observed

    def forbidden_run(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("set-id pg_receivewal must fail before execution")

    monkeypatch.setattr(os, "fstat", unsafe_root_executable)
    monkeypatch.setattr(subprocess, "run", forbidden_run)
    try:
        with pytest.raises(PostgresWalArchiveError, match=_INVALID_PARAMETERS):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                archive_descriptor,
                pg_receivewal_executable=str(executable_path),
            )
    finally:
        os.close(archive_descriptor)


def test_receiver_rejects_symlinked_receivewal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final symlink must not redirect the executable selected for child use."""
    archive_descriptor = _open_private_archive(tmp_path, "symlink-archive")
    target = _write_receivewal(tmp_path, name="trusted-pg_receivewal")
    executable_path = tmp_path / "pg_receivewal"
    executable_path.symlink_to(target)

    def forbidden_run(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("symlinked pg_receivewal must fail before execution")

    monkeypatch.setattr(subprocess, "run", forbidden_run)
    try:
        with pytest.raises(PostgresWalArchiveError, match=_INVALID_PARAMETERS):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                archive_descriptor,
                pg_receivewal_executable=str(executable_path),
            )
    finally:
        os.close(archive_descriptor)


def test_missing_receivewal_has_one_content_free_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing executable must not disclose the selected host path."""

    def missing_open(*_args: object, **_kwargs: object) -> NoReturn:
        raise FileNotFoundError("sensitive missing executable path")

    monkeypatch.setattr(wal_archive.os, "open", missing_open)
    with pytest.raises(
        PostgresWalArchiveError,
        match="^PostgreSQL WAL archive executable unavailable$",
    ) as caught:
        wal_archive._retain_pg_receivewal_executable("/secret/pg_receivewal")
    assert "sensitive" not in str(caught.value)
    assert "/secret" not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [OSError("sensitive executable open diagnostic"), ValueError("sensitive integer")],
)
def test_receivewal_open_failure_is_content_free(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    """OS and platform conversion failures cross the fixed parameter boundary."""

    def failed_open(*_args: object, **_kwargs: object) -> NoReturn:
        raise failure

    monkeypatch.setattr(wal_archive.os, "open", failed_open)
    with pytest.raises(PostgresWalArchiveError, match=_INVALID_PARAMETERS) as caught:
        wal_archive._retain_pg_receivewal_executable("/usr/bin/pg_receivewal")
    assert "sensitive" not in str(caught.value)


def test_receivewal_fstat_failure_closes_retained_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-open inspection failure must not leak package-owned authority."""
    close_attempts: list[int] = []

    monkeypatch.setattr(wal_archive.os, "open", lambda *_args, **_kwargs: 91)

    def failed_fstat(_file_descriptor: int) -> NoReturn:
        raise OSError("sensitive executable metadata diagnostic")

    monkeypatch.setattr(wal_archive.os, "fstat", failed_fstat)
    monkeypatch.setattr(wal_archive.os, "close", close_attempts.append)
    with pytest.raises(PostgresWalArchiveError, match=_INVALID_PARAMETERS) as caught:
        wal_archive._retain_pg_receivewal_executable("/usr/bin/pg_receivewal")
    assert "sensitive" not in str(caught.value)
    assert close_attempts == [91]


@pytest.mark.parametrize(
    ("mode", "case_name"),
    [
        (stat.S_IFDIR | 0o500, "non-regular"),
        (stat.S_IFREG | 0o520, "group-writable"),
        (stat.S_IFREG | 0o502, "other-writable"),
        (stat.S_IFREG | 0o400, "non-executable"),
    ],
)
def test_receiver_rejects_unsafe_root_owned_receivewal_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
    case_name: str,
) -> None:
    """Only an executable immutable regular system-tool inode may reach the child."""
    close_attempts: list[int] = []
    monkeypatch.setattr(wal_archive.os, "open", lambda *_args, **_kwargs: 92)
    monkeypatch.setattr(
        wal_archive.os,
        "fstat",
        lambda _file_descriptor: SimpleNamespace(st_mode=mode, st_uid=0),
    )
    monkeypatch.setattr(wal_archive.os, "close", close_attempts.append)
    with pytest.raises(PostgresWalArchiveError, match=_INVALID_PARAMETERS):
        wal_archive._retain_pg_receivewal_executable(
            f"/usr/bin/{case_name}-pg_receivewal"
        )
    assert close_attempts == [92]
