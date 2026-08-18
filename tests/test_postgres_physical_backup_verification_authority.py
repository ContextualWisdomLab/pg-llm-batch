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
    verify_postgres_physical_backup_tar,
)


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
