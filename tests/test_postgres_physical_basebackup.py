# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL physical base-backup execution."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import (
    PostgresPhysicalBaseBackupError,
    PostgresPhysicalBaseBackupResult,
    _close_cleanup_descriptor,
    _invalidate_output,
    create_postgres_physical_basebackup,
)


@pytest.fixture(autouse=True)
def _retain_hermetic_test_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep execution-contract tests independent of host PostgreSQL packaging."""

    def retain_test_executable(_path: str) -> int:
        return os.open(os.devnull, os.O_RDONLY)

    monkeypatch.setattr(
        physical_basebackup,
        "_retain_pg_basebackup_executable",
        retain_test_executable,
    )


def _open_private_output(tmp_path: Path, name: str = "basebackup.tar") -> tuple[Path, int]:
    path = tmp_path / name
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


def _successful_run(
    arguments: list[str],
    **kwargs: object,
) -> subprocess.CompletedProcess[bytes]:
    output_descriptor = kwargs["stdout"]
    assert type(output_descriptor) is int
    os.write(output_descriptor, b"physical-basebackup-tar")
    return subprocess.CompletedProcess(arguments, 0)


def test_success_uses_single_tablespace_tar_fetch_and_restricted_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful physical backup is a private tar stream with fetched WAL."""
    path, descriptor = _open_private_output(tmp_path)
    monkeypatch.setenv("PGPASSWORD", "secret-password")
    monkeypatch.setenv("PGPASSFILE", "/run/secrets/pgpass")
    monkeypatch.delenv("PGSERVICEFILE", raising=False)
    monkeypatch.setenv("PGHOST", "must-not-inherit")
    monkeypatch.setenv("PGSERVICE", "must-be-overridden")
    captured: dict[str, object] = {}

    def recording_run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["arguments"] = arguments
        captured.update(kwargs)
        return _successful_run(arguments, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    try:
        result = create_postgres_physical_basebackup(
            "physical_backup_source",
            descriptor,
            pg_basebackup_executable="/usr/lib/postgresql/18/bin/pg_basebackup",
            timeout_seconds=7200,
            connect_timeout_seconds=21,
        )
        assert result == PostgresPhysicalBaseBackupResult(size_bytes=23)
        assert path.read_bytes() == b"physical-basebackup-tar"
        assert captured["arguments"] == [
            "/usr/lib/postgresql/18/bin/pg_basebackup",
            "--pgdata=-",
            "--format=tar",
            "--wal-method=fetch",
            "--checkpoint=spread",
            "--manifest-checksums=SHA256",
            "--no-password",
        ]
        assert captured["stdin"] is subprocess.DEVNULL
        assert captured["stderr"] is subprocess.DEVNULL
        private_stdout = captured["stdout"]
        assert type(private_stdout) is int
        assert private_stdout != descriptor
        assert captured["timeout"] == 7200
        assert captured["check"] is False
        assert captured["close_fds"] is True
        assert captured["env"] == {
            "PGPASSWORD": "secret-password",
            "PGPASSFILE": "/run/secrets/pgpass",
            "PGSERVICE": "physical_backup_source",
            "PGCONNECT_TIMEOUT": "21",
        }
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_name", ""),
        ("service_name", "contains space"),
        ("service_name", "x" * 65),
        ("service_name", 1),
        ("output_descriptor", True),
        ("output_descriptor", -1),
        ("pg_basebackup_executable", "pg_basebackup"),
        ("pg_basebackup_executable", "/usr/bin/not-basebackup"),
        ("pg_basebackup_executable", 1),
        ("timeout_seconds", True),
        ("timeout_seconds", 0),
        ("timeout_seconds", 86_401),
        ("connect_timeout_seconds", True),
        ("connect_timeout_seconds", 0),
        ("connect_timeout_seconds", 61),
    ],
)
def test_invalid_execution_authority_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    """Exact types, service syntax, executable identity, and budgets fail closed."""
    _path, descriptor = _open_private_output(tmp_path)
    arguments: dict[str, object] = {
        "service_name": "physical_backup_source",
        "output_descriptor": descriptor,
        "pg_basebackup_executable": "/usr/bin/pg_basebackup",
        "timeout_seconds": 1800,
        "connect_timeout_seconds": 15,
    }
    arguments[field] = value

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("invalid parameters must not execute pg_basebackup")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^invalid PostgreSQL physical base-backup parameters$",
        ):
            create_postgres_physical_basebackup(**arguments)  # type: ignore[arg-type]
    finally:
        os.close(descriptor)


def test_output_must_be_empty_regular_owner_only_single_link_at_offset_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup bytes cannot target stale, shared, permissive, or non-regular storage."""
    monkeypatch.setattr(subprocess, "run", _successful_run)

    path, descriptor = _open_private_output(tmp_path, "nonempty.tar")
    os.write(descriptor, b"stale")
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="private empty regular file"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(descriptor)

    _path, descriptor = _open_private_output(tmp_path, "offset.tar")
    os.lseek(descriptor, 1, os.SEEK_SET)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="offset zero"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(descriptor)

    path, descriptor = _open_private_output(tmp_path, "permissive.tar")
    os.chmod(path, 0o640)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="owner-only"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(descriptor)

    path, descriptor = _open_private_output(tmp_path, "linked.tar")
    os.link(path, tmp_path / "linked-copy.tar")
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="one link"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(descriptor)

    read_descriptor, write_descriptor = os.pipe()
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="private empty regular file"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                write_descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(read_descriptor)
        os.close(write_descriptor)


def test_output_inspection_and_retention_failures_are_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Descriptor inspection/dup failures do not expose OS diagnostics."""
    _path, descriptor = _open_private_output(tmp_path)
    real_fstat = os.fstat

    def broken_fstat(_fd: int) -> os.stat_result:
        raise OSError("secret inspection path")

    monkeypatch.setattr(os, "fstat", broken_fstat)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="could not be inspected") as caught:
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert "secret" not in str(caught.value)
    finally:
        monkeypatch.setattr(os, "fstat", real_fstat)
        os.close(descriptor)

    _path, descriptor = _open_private_output(tmp_path, "dup.tar")

    def broken_dup(_fd: int) -> int:
        raise OSError("secret duplicate failure")

    monkeypatch.setattr(os, "dup", broken_dup)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="could not be retained") as caught:
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert "secret" not in str(caught.value)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("secret binary path"), "executable unavailable"),
        (subprocess.TimeoutExpired(["secret"], 1), "timed out"),
        (RuntimeError("secret provider data"), "execution failed"),
    ],
)
def test_execution_failures_invalidate_original_output_and_hide_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    message: str,
) -> None:
    """Known execution failures empty the inspected file and expose no stderr/content."""
    path, descriptor = _open_private_output(tmp_path)

    def exploding_run(_arguments: list[str], **kwargs: object) -> NoReturn:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"partial-secret-backup")
        raise failure

    monkeypatch.setattr(subprocess, "run", exploding_run)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match=message) as caught:
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert "secret" not in str(caught.value)
        assert path.read_bytes() == b""
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
    finally:
        os.close(descriptor)


def test_baseexception_invalidates_original_output_and_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation-like BaseException signals preserve type while invalidating bytes."""
    path, descriptor = _open_private_output(tmp_path)

    class Cancelled(BaseException):
        pass

    def cancelling_run(_arguments: list[str], **kwargs: object) -> NoReturn:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"partial")
        raise Cancelled()

    monkeypatch.setattr(subprocess, "run", cancelling_run)
    try:
        with pytest.raises(Cancelled):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)


def test_nonstandard_or_failed_completed_process_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only an exact zero-return CompletedProcess can authorize finalization."""
    for name, result in [
        ("wrong-type.tar", object()),
        ("nonzero.tar", subprocess.CompletedProcess(["pg_basebackup"], 3)),
    ]:
        path, descriptor = _open_private_output(tmp_path, name)

        def returning_run(_arguments: list[str], **kwargs: object) -> object:
            output_descriptor = kwargs["stdout"]
            assert type(output_descriptor) is int
            os.write(output_descriptor, b"partial")
            return result

        monkeypatch.setattr(subprocess, "run", returning_run)
        try:
            with pytest.raises(PostgresPhysicalBaseBackupError):
                create_postgres_physical_basebackup(
                    "physical_backup_source",
                    descriptor,
                    pg_basebackup_executable="/usr/bin/pg_basebackup",
                )
            assert path.read_bytes() == b""
        finally:
            os.close(descriptor)


def test_success_requires_nonempty_same_private_single_link_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final acceptance rejects empty, permission-drifted, linked, or replaced output."""
    path, descriptor = _open_private_output(tmp_path, "empty.tar")

    def empty_success(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", empty_success)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="incomplete"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)

    path, descriptor = _open_private_output(tmp_path, "mode.tar")

    def permission_drift(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        result = _successful_run(arguments, **kwargs)
        os.chmod(path, 0o644)
        return result

    monkeypatch.setattr(subprocess, "run", permission_drift)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="became unsafe"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)

    path, descriptor = _open_private_output(tmp_path, "links.tar")

    def link_drift(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        result = _successful_run(arguments, **kwargs)
        os.link(path, tmp_path / "links-copy.tar")
        return result

    monkeypatch.setattr(subprocess, "run", link_drift)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="became unsafe"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)

    original_path, descriptor = _open_private_output(tmp_path, "original.tar")
    replacement_path, replacement_descriptor = _open_private_output(tmp_path, "replacement.tar")

    def descriptor_substitution(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        assert output_descriptor != descriptor
        os.write(output_descriptor, b"original-sensitive-bytes")
        os.dup2(replacement_descriptor, output_descriptor)
        os.write(output_descriptor, b"replacement-bytes")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", descriptor_substitution)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="changed during execution"):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert original_path.read_bytes() == b""
        assert replacement_path.read_bytes() == b"replacement-bytes"
    finally:
        os.close(descriptor)
        os.close(replacement_descriptor)


def test_finalize_sync_failure_invalidates_output_without_leaking_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durability/fstat failures invalidate the original tar before returning failure."""
    path, descriptor = _open_private_output(tmp_path)
    monkeypatch.setattr(subprocess, "run", _successful_run)

    def broken_fsync(_fd: int) -> None:
        raise OSError("secret filesystem path")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match="could not be finalized") as caught:
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert "secret" not in str(caught.value)
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)


def test_cleanup_helpers_are_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cleanup failures never replace the primary backup outcome."""
    monkeypatch.setattr(os, "ftruncate", lambda *_args: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(os, "lseek", lambda *_args: (_ for _ in ()).throw(OSError()))
    _invalidate_output(99)

    monkeypatch.setattr(os, "close", lambda *_args: (_ for _ in ()).throw(OSError()))
    _close_cleanup_descriptor(99)
