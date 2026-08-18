# SPDX-License-Identifier: Apache-2.0
"""Artifact-authority regressions for PostgreSQL physical-backup verification."""

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
    _close_descriptor,
    _copy_manifest_to_private_file,
    _inspect_backup_directory,
    verify_postgres_physical_backup_tar,
)


_INVALID_PARAMETERS = "^invalid PostgreSQL physical-backup verification parameters$"
_VERIFICATION_FAILED = "^PostgreSQL physical backup verification failed$"


def _private_backup_directory(tmp_path: Path, name: str) -> tuple[Path, int]:
    """Create one private directory containing a minimal stdout-style base tar."""
    directory = tmp_path / name
    directory.mkdir(mode=0o700)
    archive_path = directory / "base.tar"
    manifest = b'{"PostgreSQL-Backup-Manifest-Version":2,"Files":[]}\n'
    with tarfile.open(archive_path, mode="w") as archive:
        version_bytes = b"18\n"
        version = tarfile.TarInfo("PG_VERSION")
        version.size = len(version_bytes)
        archive.addfile(version, io.BytesIO(version_bytes))
        manifest_member = tarfile.TarInfo("backup_manifest")
        manifest_member.size = len(manifest)
        archive.addfile(manifest_member, io.BytesIO(manifest))
    os.chmod(archive_path, 0o600)
    return directory, os.open(directory, os.O_RDONLY | os.O_DIRECTORY)


def _forbidden_subprocess(*_args: object, **_kwargs: object) -> NoReturn:
    """Fail if mutable or ambiguous backup authority reaches PostgreSQL."""
    raise AssertionError("unsafe backup authority must fail before pg_verifybackup")


def _open_private_base_tar(directory_descriptor: int) -> int:
    """Open the private base tar through the same relative authority under test."""
    return os.open(
        "base.tar",
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=directory_descriptor,
    )


def test_group_writable_base_tar_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another local principal must not retain write authority to verified bytes."""
    directory, descriptor = _private_backup_directory(tmp_path, "group-writable")
    os.chmod(directory / "base.tar", 0o660)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_VERIFICATION_FAILED):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


def test_hard_linked_base_tar_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second pathname must not retain mutation authority to accepted backup bytes."""
    directory, descriptor = _private_backup_directory(tmp_path, "hard-linked")
    os.link(directory / "base.tar", tmp_path / "external-backup-link.tar")
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_VERIFICATION_FAILED):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


def test_extra_directory_entry_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-tablespace stdout contract accepts exactly one base tar entry."""
    directory, descriptor = _private_backup_directory(tmp_path, "extra-entry")
    (directory / "unexpected.tar").write_bytes(b"unreviewed sibling")
    os.chmod(directory / "unexpected.tar", 0o600)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresPhysicalBackupVerificationError, match=_VERIFICATION_FAILED):
            verify_postgres_physical_backup_tar(
                descriptor,
                pg_verifybackup_executable="/usr/bin/pg_verifybackup",
            )
    finally:
        os.close(descriptor)


def test_descriptor_cleanup_is_best_effort_for_already_closed_authority() -> None:
    """A failed best-effort close must not replace the primary verification outcome."""
    _close_descriptor(-1)


def test_directory_inspection_failure_is_content_free() -> None:
    """An unreadable retained directory descriptor crosses the fixed invalid boundary."""
    with pytest.raises(
        PostgresPhysicalBackupVerificationError,
        match=_INVALID_PARAMETERS,
    ):
        _inspect_backup_directory(-1)


def test_manifest_member_read_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member-stream read failure cannot expose archive or host diagnostics."""
    class FailingManifestStream(io.BytesIO):
        def read(self, *_args: object, **_kwargs: object) -> bytes:
            raise OSError("sensitive manifest stream diagnostic")

    _directory, directory_descriptor = _private_backup_directory(
        tmp_path,
        "manifest-read-failure",
    )
    base_tar_descriptor = _open_private_base_tar(directory_descriptor)
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractfile",
        lambda *_args, **_kwargs: FailingManifestStream(b"manifest"),
    )
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ) as caught:
            _copy_manifest_to_private_file(base_tar_descriptor, io.BytesIO())
        assert "manifest stream" not in str(caught.value)
    finally:
        os.close(base_tar_descriptor)
        os.close(directory_descriptor)


def test_manifest_stream_interrupt_remains_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process-level interruption while reading a member stream is not rewritten."""
    class InterruptingManifestStream(io.BytesIO):
        def read(self, *_args: object, **_kwargs: object) -> bytes:
            raise KeyboardInterrupt

    _directory, directory_descriptor = _private_backup_directory(
        tmp_path,
        "manifest-interrupt",
    )
    base_tar_descriptor = _open_private_base_tar(directory_descriptor)
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractfile",
        lambda *_args, **_kwargs: InterruptingManifestStream(b"manifest"),
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            _copy_manifest_to_private_file(base_tar_descriptor, io.BytesIO())
    finally:
        os.close(base_tar_descriptor)
        os.close(directory_descriptor)


def test_manifest_staging_requires_real_descriptor_authority(tmp_path: Path) -> None:
    """A descriptor-less staging object fails closed after an otherwise valid copy."""
    _directory, directory_descriptor = _private_backup_directory(
        tmp_path,
        "manifest-no-descriptor",
    )
    base_tar_descriptor = _open_private_base_tar(directory_descriptor)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ):
            _copy_manifest_to_private_file(base_tar_descriptor, io.BytesIO())
    finally:
        os.close(base_tar_descriptor)
        os.close(directory_descriptor)
