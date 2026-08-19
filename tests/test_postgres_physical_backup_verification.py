# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL physical-backup verification."""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_physical_backup_verification import (
    PostgresPhysicalBackupVerificationError,
    PostgresPhysicalBackupVerificationResult,
    verify_postgres_physical_backup_tar,
)


_INVALID_PARAMETERS = "^invalid PostgreSQL physical-backup verification parameters$"
_MANIFEST_ERROR = "^PostgreSQL physical backup must contain one regular backup manifest$"
_VERIFICATION_FAILED = "^PostgreSQL physical backup verification failed$"
_TRUSTED_EXECUTABLE_BYTES = b"trusted pg_verifybackup binary\n"
_VERIFIER_IDENTITIES: set[tuple[int, int]] = set()


def _with_owner(status: os.stat_result, user_id: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit owner identity."""
    fields = list(status)
    fields[4] = user_id
    return os.stat_result(fields)


@pytest.fixture(autouse=True)
def _model_root_owned_verifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Model temporary verifier fixtures as root-owned system executables."""
    _VERIFIER_IDENTITIES.clear()
    real_fstat = os.fstat

    def root_owned_verifier_metadata(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) in _VERIFIER_IDENTITIES:
            return _with_owner(status, 0)
        return status

    monkeypatch.setattr(os, "fstat", root_owned_verifier_metadata)
    yield
    _VERIFIER_IDENTITIES.clear()


def _write_stdout_style_base_tar(
    directory: Path,
    *,
    duplicate_manifest: bool = False,
    include_manifest: bool = True,
    manifest_is_regular: bool = True,
) -> int:
    """Create the single-tablespace tar shape emitted by pg_basebackup -D -."""
    archive_path = directory / "base.tar"
    manifest = (
        b'{"PostgreSQL-Backup-Manifest-Version":2,"System-Identifier":1,'
        b'"Files":[],"WAL-Ranges":[],"Manifest-Checksum":"00"}\n'
    )
    with tarfile.open(archive_path, mode="w") as archive:
        payload = b"18\n"
        version = tarfile.TarInfo("PG_VERSION")
        version.size = len(payload)
        archive.addfile(version, io.BytesIO(payload))
        if include_manifest:
            for _ in range(2 if duplicate_manifest else 1):
                member = tarfile.TarInfo("backup_manifest")
                if manifest_is_regular:
                    member.size = len(manifest)
                    archive.addfile(member, io.BytesIO(manifest))
                else:
                    member.type = tarfile.DIRTYPE
                    archive.addfile(member)
    os.chmod(archive_path, 0o600)
    return os.open(directory, os.O_RDONLY | os.O_DIRECTORY)


def _write_private_pg_verifybackup(tmp_path: Path) -> Path:
    """Create and register one root-owned verifier fixture token."""
    executable = tmp_path / "pg_verifybackup"
    executable.write_bytes(_TRUSTED_EXECUTABLE_BYTES)
    executable.chmod(0o500)
    status = os.stat(executable, follow_symlinks=False)
    _VERIFIER_IDENTITIES.add((status.st_dev, status.st_ino))
    return executable


def test_success_verifies_stdout_tar_with_descriptor_backed_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verifier adapts manifest and executable authority to retained descriptors."""
    backup_directory = tmp_path / "backup"
    backup_directory.mkdir(mode=0o700)
    directory_descriptor = _write_stdout_style_base_tar(backup_directory)
    executable_path = _write_private_pg_verifybackup(tmp_path)
    captured: dict[str, object] = {}

    def successful_run(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        captured["arguments"] = arguments
        captured.update(kwargs)
        executable_fd = int(arguments[0].rsplit("/", 1)[-1])
        assert os.pread(executable_fd, len(_TRUSTED_EXECUTABLE_BYTES), 0) == (
            _TRUSTED_EXECUTABLE_BYTES
        )
        manifest_argument = next(
            argument for argument in arguments if argument.startswith("--manifest-path=")
        )
        manifest_fd = int(manifest_argument.rsplit("/", 1)[-1])
        assert b'"PostgreSQL-Backup-Manifest-Version":2' in os.pread(
            manifest_fd, 4096, 0
        )
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", successful_run)
    try:
        result = verify_postgres_physical_backup_tar(
            directory_descriptor,
            pg_verifybackup_executable=str(executable_path),
            timeout_seconds=1800,
        )
        assert result == PostgresPhysicalBackupVerificationResult(verified=True)
        arguments = captured["arguments"]
        assert type(arguments) is list
        assert arguments[0].startswith("/proc/self/fd/")
        assert "--format=tar" in arguments
        assert "--no-parse-wal" in arguments
        assert "--quiet" in arguments
        assert "--exit-on-error" in arguments
        assert arguments[-1].startswith("/proc/self/fd/")
        assert captured["stdin"] is subprocess.DEVNULL
        assert captured["stdout"] is subprocess.DEVNULL
        assert captured["stderr"] is subprocess.DEVNULL
        assert captured["check"] is False
        assert captured["close_fds"] is True
        assert captured["timeout"] == 1800
        inherited = captured["pass_fds"]
        assert type(inherited) is tuple
        assert len(inherited) == 4
        assert int(arguments[0].rsplit("/", 1)[-1]) in inherited
        assert int(arguments[-1].rsplit("/", 1)[-1]) in inherited
    finally:
        os.close(directory_descriptor)


def test_executable_path_replacement_cannot_change_retained_child_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Late pathname replacement cannot swap the executable inode given to PostgreSQL."""
    backup_directory = tmp_path / "backup-executable-race"
    backup_directory.mkdir(mode=0o700)
    directory_descriptor = _write_stdout_style_base_tar(backup_directory)
    executable_path = _write_private_pg_verifybackup(tmp_path)

    def replace_path_then_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        retained_path = tmp_path / "retained-pg_verifybackup"
        executable_path.rename(retained_path)
        executable_path.write_bytes(b"attacker replacement\n")
        executable_path.chmod(0o500)
        executable_fd = int(arguments[0].rsplit("/", 1)[-1])
        assert os.pread(executable_fd, len(_TRUSTED_EXECUTABLE_BYTES), 0) == (
            _TRUSTED_EXECUTABLE_BYTES
        )
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", replace_path_then_run)
    try:
        assert verify_postgres_physical_backup_tar(
            directory_descriptor,
            pg_verifybackup_executable=str(executable_path),
        ).verified
    finally:
        os.close(directory_descriptor)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backup_directory_descriptor", True),
        ("backup_directory_descriptor", -1),
        ("pg_verifybackup_executable", "pg_verifybackup"),
        ("pg_verifybackup_executable", "/usr/bin/not-pg-verifybackup"),
        ("pg_verifybackup_executable", 1),
        ("timeout_seconds", True),
        ("timeout_seconds", 0),
        ("timeout_seconds", 86_401),
    ],
)
def test_invalid_authority_fails_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    """Descriptors, executable identity, and execution budget are exact and bounded."""
    backup_directory = tmp_path / "backup-invalid"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    arguments: dict[str, object] = {
        "backup_directory_descriptor": descriptor,
        "pg_verifybackup_executable": "/usr/bin/pg_verifybackup",
        "timeout_seconds": 1800,
    }
    arguments[field] = value

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("invalid authority must not execute pg_verifybackup")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_INVALID_PARAMETERS,
        ):
            verify_postgres_physical_backup_tar(**arguments)  # type: ignore[arg-type]
    finally:
        os.close(descriptor)


def test_closed_directory_descriptor_is_content_free_invalid_authority(
    tmp_path: Path,
) -> None:
    """Descriptor-retention failure must not leak an operating-system diagnostic."""
    backup_directory = tmp_path / "backup-closed"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    os.close(descriptor)
    with pytest.raises(
        PostgresPhysicalBackupVerificationError,
        match=_INVALID_PARAMETERS,
    ):
        verify_postgres_physical_backup_tar(
            descriptor,
            pg_verifybackup_executable="/usr/bin/pg_verifybackup",
        )


def test_writable_backup_directory_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group-writable backup authority cannot be trusted for verification."""
    backup_directory = tmp_path / "backup-writable"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    os.chmod(backup_directory, 0o770)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("unsafe directory must fail before pg_verifybackup")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_INVALID_PARAMETERS):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


def test_group_writable_verifier_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another local principal must not retain write authority to verifier bytes."""
    backup_directory = tmp_path / "backup-writable-verifier"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    executable_path = _write_private_pg_verifybackup(tmp_path)
    executable_path.chmod(0o570)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("unsafe executable must fail before subprocess execution")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_INVALID_PARAMETERS):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable=str(executable_path),
            )
    finally:
        os.close(descriptor)


def test_symlinked_verifier_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifier authority must not be redirected through a caller-controlled symlink."""
    backup_directory = tmp_path / "backup-symlinked-verifier"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    target = tmp_path / "trusted-verifier-target"
    target.write_bytes(_TRUSTED_EXECUTABLE_BYTES)
    target.chmod(0o500)
    executable_path = tmp_path / "pg_verifybackup"
    executable_path.symlink_to(target)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("symlinked executable must fail before subprocess execution")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_INVALID_PARAMETERS):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable=str(executable_path),
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("include_manifest", "manifest_is_regular", "duplicate_manifest"),
    [
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_ambiguous_or_nonregular_manifest_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    include_manifest: bool,
    manifest_is_regular: bool,
    duplicate_manifest: bool,
) -> None:
    """Exactly one regular injected manifest is required before child execution."""
    backup_directory = tmp_path / "backup-manifest"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(
        backup_directory,
        include_manifest=include_manifest,
        manifest_is_regular=manifest_is_regular,
        duplicate_manifest=duplicate_manifest,
    )

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("invalid manifest must not execute pg_verifybackup")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_MANIFEST_ERROR):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


def test_manifest_extraction_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected absence of a regular member stream fails closed."""
    backup_directory = tmp_path / "backup-extract"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda *_args, **_kwargs: None)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_MANIFEST_ERROR):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("base_tar_shape", ["missing", "directory", "symlink", "corrupt"])
def test_invalid_base_tar_fails_content_free(
    tmp_path: Path,
    base_tar_shape: str,
) -> None:
    """Missing, redirected, nonregular, or malformed backup bytes fail closed."""
    backup_directory = tmp_path / f"backup-{base_tar_shape}"
    backup_directory.mkdir(mode=0o700)
    base_tar = backup_directory / "base.tar"
    if base_tar_shape == "directory":
        base_tar.mkdir()
    elif base_tar_shape == "symlink":
        target = tmp_path / "outside.tar"
        target.write_bytes(b"outside")
        base_tar.symlink_to(target)
    elif base_tar_shape == "corrupt":
        base_tar.write_bytes(b"not a tar archive")
    descriptor = os.open(backup_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_VERIFICATION_FAILED):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


def test_manifest_descriptor_retention_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FD exhaustion after base-tar open must not leak host diagnostics."""
    backup_directory = tmp_path / "backup-fd-exhausted"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    real_dup = os.dup
    calls = 0

    def fail_second_dup(file_descriptor: int) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sensitive descriptor-table diagnostic")
        return real_dup(file_descriptor)

    monkeypatch.setattr(os, "dup", fail_second_dup)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ) as caught:
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
        assert "descriptor-table" not in str(caught.value)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "effect",
    [
        subprocess.TimeoutExpired(["pg_verifybackup"], 1800),
        OSError("sensitive executable diagnostic"),
        RuntimeError("sensitive adapter diagnostic"),
    ],
)
def test_verifier_execution_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    effect: BaseException,
) -> None:
    """Timeout, OS, and ordinary adapter failures cross one fixed boundary."""
    backup_directory = tmp_path / "backup-execution-failed"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    executable_path = _write_private_pg_verifybackup(tmp_path)

    def failed_run(*_args: object, **_kwargs: object) -> NoReturn:
        raise effect

    monkeypatch.setattr(subprocess, "run", failed_run)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_VERIFICATION_FAILED):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable=str(executable_path),
            )
    finally:
        os.close(descriptor)


def test_keyboard_interrupt_remains_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process-level interruption is not rewritten as a package verification error."""
    backup_directory = tmp_path / "backup-interrupt"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    executable_path = _write_private_pg_verifybackup(tmp_path)

    def interrupted(*_args: object, **_kwargs: object) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "run", interrupted)
    try:
        with pytest.raises(KeyboardInterrupt):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable=str(executable_path),
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "result",
    [
        subprocess.CompletedProcess(["pg_verifybackup"], 1),
        object(),
    ],
)
def test_verifier_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: object,
) -> None:
    """Non-success and malformed subprocess results never expose backup details."""
    backup_directory = tmp_path / "backup-failed"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)
    executable_path = _write_private_pg_verifybackup(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: result)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ) as caught:
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable=str(executable_path),
            )
        assert "backup-failed" not in str(caught.value)
    finally:
        os.close(descriptor)
