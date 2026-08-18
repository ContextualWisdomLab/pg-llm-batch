# SPDX-License-Identifier: Apache-2.0
"""Resource-budget regressions for physical-backup verification staging."""

from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import BinaryIO, NoReturn

import pytest

import pg_llm_batch.postgres_physical_backup_verification as verification_module
from pg_llm_batch.postgres_physical_backup_verification import (
    PostgresPhysicalBackupVerificationError,
    _copy_manifest_to_private_file,
)


_TEST_MAX_ARCHIVE_MEMBERS = 3
_TEST_MAX_MANIFEST_BYTES = 8
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
            manifest.size = _TEST_MAX_MANIFEST_BYTES + 1
            yield manifest
            return
        for index in range(_TEST_MAX_ARCHIVE_MEMBERS + 1):
            yield tarfile.TarInfo(f"member-{index}")
        raise AssertionError("archive enumeration exceeded the reviewed member budget")

    def getmembers(self) -> list[tarfile.TarInfo]:
        """Model the current eager enumeration path so the RED is deterministic."""
        return list(self)

    def extractfile(self, _member: tarfile.TarInfo) -> BinaryIO:
        """Prove oversized manifest metadata is rejected before stream extraction."""
        raise AssertionError("oversized manifest must be rejected before extraction")


class _BoundedDirectoryEntries:
    """Model a huge directory while permitting inspection of at most two entries."""

    def __init__(self) -> None:
        self._index = 0

    def __enter__(self) -> _BoundedDirectoryEntries:
        """Return this synthetic directory iterator."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Leave the synthetic directory iterator without side effects."""

    def __iter__(self) -> _BoundedDirectoryEntries:
        """Return the bounded iterator itself."""
        return self

    def __next__(self) -> SimpleNamespace:
        """Yield two entries, then prove the implementation did not scan farther."""
        self._index += 1
        if self._index == 1:
            return SimpleNamespace(name="base.tar")
        if self._index == 2:
            return SimpleNamespace(name="unexpected-entry")
        raise AssertionError("directory enumeration exceeded the second entry")


def _forbidden_listdir(*_args: object, **_kwargs: object) -> NoReturn:
    """Prove directory validation never materializes the complete entry list."""
    raise AssertionError("directory validation must use bounded streaming enumeration")


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
    monkeypatch.setattr(
        verification_module,
        "_MAX_ARCHIVE_MEMBERS",
        _TEST_MAX_ARCHIVE_MEMBERS,
        raising=False,
    )
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
    monkeypatch.setattr(
        verification_module,
        "_MAX_MANIFEST_BYTES",
        _TEST_MAX_MANIFEST_BYTES,
        raising=False,
    )
    try:
        with tempfile.TemporaryFile(mode="w+b") as manifest_file:
            with pytest.raises(
                PostgresPhysicalBackupVerificationError,
                match=_MANIFEST_ERROR,
            ):
                _copy_manifest_to_private_file(base_tar_descriptor, manifest_file)
    finally:
        os.close(base_tar_descriptor)


def test_directory_entry_enumeration_stops_after_second_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A huge malformed backup directory must fail without materializing all names."""
    directory_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(os, "listdir", _forbidden_listdir)
    monkeypatch.setattr(os, "scandir", lambda _descriptor: _BoundedDirectoryEntries())
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ):
            verification_module._inspect_backup_directory(directory_descriptor)
    finally:
        os.close(directory_descriptor)
