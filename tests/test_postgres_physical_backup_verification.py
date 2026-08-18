# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL physical-backup verification."""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_physical_backup_verification import (
    PostgresPhysicalBackupVerificationError,
    PostgresPhysicalBackupVerificationResult,
    verify_postgres_physical_backup_tar,
)


def _write_stdout_style_base_tar(directory: Path, *, duplicate_manifest: bool = False) -> int:
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
        for _ in range(2 if duplicate_manifest else 1):
            member = tarfile.TarInfo("backup_manifest")
            member.size = len(manifest)
            archive.addfile(member, io.BytesIO(manifest))
    os.chmod(archive_path, 0o600)
    return os.open(directory, os.O_RDONLY | os.O_DIRECTORY)


def test_success_verifies_stdout_tar_with_separate_memfd_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verifier adapts the injected stdout manifest without filesystem extraction."""
    backup_directory = tmp_path / "backup"
    backup_directory.mkdir(mode=0o700)
    directory_descriptor = _write_stdout_style_base_tar(backup_directory)
    captured: dict[str, object] = {}

    def successful_run(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        captured["arguments"] = arguments
        captured.update(kwargs)
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
            pg_verifybackup_executable="/usr/lib/postgresql/18/bin/pg_verifybackup",
            timeout_seconds=1800,
        )
        assert result == PostgresPhysicalBackupVerificationResult(verified=True)
        arguments = captured["arguments"]
        assert type(arguments) is list
        assert arguments[0] == "/usr/lib/postgresql/18/bin/pg_verifybackup"
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
        assert len(inherited) == 2
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
            match="^invalid PostgreSQL physical-backup verification parameters$",
        ):
            verify_postgres_physical_backup_tar(**arguments)  # type: ignore[arg-type]
    finally:
        os.close(descriptor)


def test_duplicate_injected_manifest_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguous manifest authority in an archive fails closed."""
    backup_directory = tmp_path / "backup-duplicate"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(
        backup_directory, duplicate_manifest=True
    )

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("ambiguous manifest must not execute pg_verifybackup")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match="^PostgreSQL physical backup must contain one regular backup manifest$",
        ):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


def test_verifier_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg_verifybackup diagnostics never cross the package boundary."""
    backup_directory = tmp_path / "backup-failed"
    backup_directory.mkdir(mode=0o700)
    descriptor = _write_stdout_style_base_tar(backup_directory)

    def failed_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(arguments, 1)

    monkeypatch.setattr(subprocess, "run", failed_run)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match="^PostgreSQL physical backup verification failed$",
        ) as caught:
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
        assert "backup-failed" not in str(caught.value)
    finally:
        os.close(descriptor)
