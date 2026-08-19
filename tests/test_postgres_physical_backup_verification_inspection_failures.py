# SPDX-License-Identifier: Apache-2.0
"""Inspection-failure regressions for PostgreSQL physical-backup verification."""

from __future__ import annotations

import io
import os
import tarfile
import tempfile
from pathlib import Path

import pytest

import pg_llm_batch.postgres_physical_backup_verification as physical_backup_verification
from pg_llm_batch.postgres_physical_backup_verification import (
    PostgresPhysicalBackupVerificationError,
    _copy_manifest_to_private_file,
    _open_base_tar,
    _retain_pg_verifybackup_executable,
)


_INVALID_PARAMETERS = "^invalid PostgreSQL physical-backup verification parameters$"
_MANIFEST_ERROR = "^PostgreSQL physical backup must contain one regular backup manifest$"
_VERIFICATION_FAILED = "^PostgreSQL physical backup verification failed$"


def _raise_fstat_error(_file_descriptor: int) -> os.stat_result:
    """Model a local inode-inspection failure after a non-blocking open succeeds."""
    raise OSError("sensitive fstat diagnostic")


def _private_stdout_tar(tmp_path: Path) -> tuple[int, int]:
    """Create and open one private directory plus minimal stdout-format base tar."""
    backup_directory = tmp_path / "backup"
    backup_directory.mkdir(mode=0o700)
    base_tar_path = backup_directory / "base.tar"
    manifest = b'{"PostgreSQL-Backup-Manifest-Version":2,"Files":[]}\n'
    with tarfile.open(base_tar_path, mode="w") as archive:
        manifest_member = tarfile.TarInfo("backup_manifest")
        manifest_member.size = len(manifest)
        archive.addfile(manifest_member, io.BytesIO(manifest))
    base_tar_path.chmod(0o600)
    directory_descriptor = os.open(
        backup_directory,
        os.O_RDONLY | os.O_DIRECTORY,
    )
    base_tar_descriptor = os.open(
        "base.tar",
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=directory_descriptor,
    )
    return directory_descriptor, base_tar_descriptor


def test_verifier_inode_inspection_failure_is_content_free_and_closes_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-open verifier fstat failure must cross the invalid-parameter boundary."""
    executable_path = tmp_path / "pg_verifybackup"
    executable_path.write_bytes(b"not executed")
    executable_path.chmod(0o700)
    opened_descriptors: list[int] = []
    original_open = os.open

    def capturing_open(
        path: str | os.PathLike[str],
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        """Capture the descriptor opened by the verifier-retention helper."""
        descriptor = original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        opened_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", capturing_open)
    monkeypatch.setattr(os, "fstat", _raise_fstat_error)

    with pytest.raises(
        PostgresPhysicalBackupVerificationError,
        match=_INVALID_PARAMETERS,
    ) as caught:
        _retain_pg_verifybackup_executable(str(executable_path))

    assert "fstat diagnostic" not in str(caught.value)
    assert len(opened_descriptors) == 1
    descriptor = opened_descriptors[0]
    monkeypatch.undo()
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_base_tar_inode_inspection_failure_is_content_free_and_closes_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-open base-tar fstat failure must close package-owned authority."""
    backup_directory = tmp_path / "backup-inspection"
    backup_directory.mkdir(mode=0o700)
    base_tar_path = backup_directory / "base.tar"
    base_tar_path.write_bytes(b"placeholder")
    base_tar_path.chmod(0o600)
    directory_descriptor = os.open(
        backup_directory,
        os.O_RDONLY | os.O_DIRECTORY,
    )
    opened_descriptors: list[int] = []
    original_open = os.open

    def capturing_open(
        path: str | os.PathLike[str],
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        """Capture only the descriptor opened relative to retained directory authority."""
        descriptor = original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        opened_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", capturing_open)
    monkeypatch.setattr(os, "fstat", _raise_fstat_error)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ) as caught:
            _open_base_tar(directory_descriptor)
        assert "fstat diagnostic" not in str(caught.value)
        assert len(opened_descriptors) == 1
        descriptor = opened_descriptors[0]
        monkeypatch.undo()
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        os.close(directory_descriptor)


def test_missing_manifest_stream_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regular manifest whose stream cannot be opened must fail closed."""
    directory_descriptor, base_tar_descriptor = _private_stdout_tar(tmp_path)
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractfile",
        lambda *_args, **_kwargs: None,
    )
    try:
        with tempfile.TemporaryFile(mode="w+b") as manifest_file:
            with pytest.raises(
                PostgresPhysicalBackupVerificationError,
                match=_MANIFEST_ERROR,
            ):
                _copy_manifest_to_private_file(
                    base_tar_descriptor,
                    manifest_file,
                )
    finally:
        os.close(base_tar_descriptor)
        os.close(directory_descriptor)


def test_truncated_manifest_stream_fails_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared manifest whose stream ends early must fail before verification."""
    directory_descriptor, base_tar_descriptor = _private_stdout_tar(tmp_path)
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractfile",
        lambda *_args, **_kwargs: io.BytesIO(),
    )
    try:
        with tempfile.TemporaryFile(mode="w+b") as manifest_file:
            with pytest.raises(
                PostgresPhysicalBackupVerificationError,
                match=_VERIFICATION_FAILED,
            ):
                _copy_manifest_to_private_file(
                    base_tar_descriptor,
                    manifest_file,
                )
    finally:
        os.close(base_tar_descriptor)
        os.close(directory_descriptor)


def test_regular_manifest_stream_is_copied_to_private_staging_file(
    tmp_path: Path,
) -> None:
    """A valid regular manifest must cross the real streaming copy path."""
    directory_descriptor, base_tar_descriptor = _private_stdout_tar(tmp_path)
    expected_manifest = b'{"PostgreSQL-Backup-Manifest-Version":2,"Files":[]}\n'
    try:
        with tempfile.TemporaryFile(mode="w+b") as manifest_file:
            manifest_descriptor = _copy_manifest_to_private_file(
                base_tar_descriptor,
                manifest_file,
            )
            assert manifest_descriptor == manifest_file.fileno()
            assert manifest_file.read() == expected_manifest
    finally:
        os.close(base_tar_descriptor)
        os.close(directory_descriptor)


def test_total_timeout_expires_during_manifest_staging_before_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public timeout must bound pre-verifier tar work as well as subprocess work."""
    directory_descriptor, base_tar_descriptor = _private_stdout_tar(tmp_path)
    os.close(base_tar_descriptor)
    monotonic_values = iter((100.0, 100.1, 100.2, 100.3, 100.4, 100.5, 101.1))
    monkeypatch.setattr(
        physical_backup_verification,
        "_monotonic",
        lambda: next(monotonic_values),
        raising=False,
    )

    def forbidden_verifier(**_kwargs: object) -> None:
        """Fail if expired pre-verifier work reaches PostgreSQL execution."""
        pytest.fail("pg_verifybackup must not run after the total timeout expires")

    monkeypatch.setattr(
        physical_backup_verification,
        "_run_pg_verifybackup",
        forbidden_verifier,
    )
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ):
            physical_backup_verification.verify_postgres_physical_backup_tar(
                directory_descriptor,
                pg_verifybackup_executable=str(tmp_path / "pg_verifybackup"),
                timeout_seconds=1,
            )
    finally:
        os.close(directory_descriptor)
