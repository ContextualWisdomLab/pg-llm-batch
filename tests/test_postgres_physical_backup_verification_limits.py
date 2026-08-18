# SPDX-License-Identifier: Apache-2.0
"""Resource-budget regressions for physical-backup verification staging."""

from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

import pytest

from pg_llm_batch.postgres_physical_backup_verification import (
    PostgresPhysicalBackupVerificationError,
    _copy_manifest_to_private_file,
)


_MAX_ARCHIVE_MEMBERS = 65_536
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_MANIFEST_ERROR = "^PostgreSQL physical backup must contain one regular backup manifest$"
_VERIFICATION_FAILED = "^PostgreSQL physical backup verification failed$"


class _SyntheticArchive:
    """Expose finite adversarial metadata without allocating a large tar archive."""

    def __init__(self, *, oversized_manifest: bool) -> None:
        self._oversized_manifest = oversized_manifest

    def __enter__(self) -> _SyntheticArchive:
        """Return this synthetic archive context."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Leave the synthetic archive context without side effects."""

    def __iter__(self):  # type: ignore[no-untyped-def]
        """Yield adversarial metadata and fail if enumeration is not bounded."""
        if self._oversized_manifest:
            manifest = tarfile.TarInfo("backup_manifest")
            manifest.size = _MAX_MANIFEST_BYTES + 1
            yield manifest
            return
        for index in range(_MAX_ARCHIVE_MEMBERS + 1):
            yield tarfile.TarInfo(f"member-{index}")
        raise AssertionError("archive enumeration exceeded the reviewed member budget")

    def getmembers(self) -> list[tarfile.TarInfo]:
        """Model the current eager enumeration path so the RED is deterministic."""
        return list(self)

    def extractfile(self, _member: tarfile.TarInfo) -> BinaryIO:
        """Prove oversized manifest metadata is rejected before stream extraction."""
        raise AssertionError("oversized manifest must be rejected before extraction")


def _open_placeholder_tar(tmp_path: Path) -> int:
    """Return one harmless descriptor because tar parsing is synthetic in these tests."""
    archive_path = tmp_path / "base.tar"
    archive_path.write_bytes(b"placeholder")
    archive_path.chmod(0o600)
    return os.open(archive_path, os.O_RDONLY)


def test_archive_member_enumeration_is_bounded_before_manifest_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member-explosive tar must fail before Python enumerates unbounded metadata."""
    base_tar_descriptor = _open_placeholder_tar(tmp_path)
    archive = _SyntheticArchive(oversized_manifest=False)
    monkeypatch.setattr(tarfile, "open", lambda **_kwargs: archive)
    try:
        with tempfile.TemporaryFile(mode="w+b") as manifest_file:
            with pytest.raises(
                PostgresPhysicalBackupVerificationError,
                match=_VERIFICATION_FAILED,
            ):
                _copy_manifest_to_private_file(base_tar_descriptor, manifest_file)
    finally:
        os.close(base_tar_descriptor)


def test_declared_manifest_size_is_bounded_before_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized manifest must fail before extraction or unbounded staging copy."""
    base_tar_descriptor = _open_placeholder_tar(tmp_path)
    archive = _SyntheticArchive(oversized_manifest=True)
    monkeypatch.setattr(tarfile, "open", lambda **_kwargs: archive)
    try:
        with tempfile.TemporaryFile(mode="w+b") as manifest_file:
            with pytest.raises(
                PostgresPhysicalBackupVerificationError,
                match=_MANIFEST_ERROR,
            ):
                _copy_manifest_to_private_file(base_tar_descriptor, manifest_file)
    finally:
        os.close(base_tar_descriptor)
