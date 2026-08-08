# SPDX-License-Identifier: Apache-2.0
"""Security regressions for descriptor-bound release manifest writes."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

import pg_llm_batch.release_evidence as release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, write_release_manifest


_MANIFEST_NAME = "release-manifest.json"


def test_write_release_manifest_pins_parent_during_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep manifest bytes in the opened directory when its pathname is swapped."""
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    held_evidence = workspace / "evidence-held"
    outside = tmp_path / "outside"
    evidence.mkdir(parents=True)
    outside.mkdir()
    destination = evidence / _MANIFEST_NAME
    original_open = release_evidence.os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        path_text = os.fsdecode(path)
        if not swapped and path_text == f".{_MANIFEST_NAME}.tmp":
            evidence.rename(held_evidence)
            evidence.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(release_evidence.os, "open", swapping_open)

    write_release_manifest({"schema_version": 1}, destination)

    assert swapped
    assert not (outside / _MANIFEST_NAME).exists()
    assert json.loads(
        (held_evidence / _MANIFEST_NAME).read_text(encoding="utf-8")
    ) == {"schema_version": 1}


@pytest.mark.parametrize("unsupported_capability", ["dir_fd", "follow", "flags"])
def test_write_release_manifest_fails_without_secure_dir_fd_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsupported_capability: str,
) -> None:
    """Fail before mutation when any descriptor-relative capability is unavailable."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    if unsupported_capability == "dir_fd":
        monkeypatch.setattr(release_evidence.os, "supports_dir_fd", set())
    elif unsupported_capability == "follow":
        monkeypatch.setattr(release_evidence.os, "supports_follow_symlinks", set())
    else:
        monkeypatch.setattr(release_evidence, "_SECURE_MANIFEST_FLAGS_AVAILABLE", False)

    with pytest.raises(ReleaseEvidenceError, match="descriptor-relative no-follow"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not destination.parent.exists()


def test_write_release_manifest_rejects_invalid_destination_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a destination that has no final filename."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ReleaseEvidenceError, match="destination name is invalid"):
        write_release_manifest({"schema_version": 1}, Path("."))


def test_write_release_manifest_rejects_parent_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a relative parent component instead of escaping the selected directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    escaped = tmp_path / _MANIFEST_NAME

    with pytest.raises(ReleaseEvidenceError, match="parent traversal"):
        write_release_manifest(
            {"schema_version": 1},
            Path("..") / _MANIFEST_NAME,
        )

    assert not escaped.exists()


def test_write_release_manifest_supports_descriptor_bound_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create a relative evidence directory through the current-directory descriptor."""
    monkeypatch.chdir(tmp_path)
    destination = Path("evidence") / _MANIFEST_NAME

    write_release_manifest({"schema_version": 1}, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == {"schema_version": 1}


def test_write_release_manifest_bounds_parent_root_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convert a root-descriptor failure into a fixed release evidence error."""
    monkeypatch.chdir(tmp_path)
    original_open = release_evidence.os.open

    def failing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is None and os.fsdecode(path) == ".":
            raise PermissionError("untrusted root error")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(release_evidence.os, "open", failing_open)

    with pytest.raises(ReleaseEvidenceError, match="parent root could not be opened"):
        write_release_manifest({"schema_version": 1}, Path("evidence") / _MANIFEST_NAME)

    assert not (tmp_path / "evidence").exists()


def test_write_release_manifest_bounds_parent_creation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convert a parent-directory creation failure without exposing OS text."""
    original_mkdir = release_evidence.os.mkdir

    def failing_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if os.fsdecode(path) == "blocked-evidence":
            raise PermissionError("untrusted mkdir error")
        original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(release_evidence.os, "mkdir", failing_mkdir)
    destination = tmp_path / "blocked-evidence" / _MANIFEST_NAME

    with pytest.raises(ReleaseEvidenceError, match="parent directory could not be created"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not destination.parent.exists()


def test_write_release_manifest_bounds_destination_inspection_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convert an lstat-style destination failure into bounded diagnostics."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    original_stat = release_evidence.os.stat

    def failing_stat(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes] | int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if dir_fd is not None and os.fsdecode(path) == _MANIFEST_NAME:
            raise PermissionError("untrusted stat error")
        return original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(release_evidence.os, "stat", failing_stat)

    with pytest.raises(ReleaseEvidenceError, match="destination could not be inspected"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not destination.exists()


def test_write_release_manifest_rejects_nonregular_destination(tmp_path: Path) -> None:
    """Refuse to atomically replace a directory or other non-regular object."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    destination.mkdir(parents=True)

    with pytest.raises(ReleaseEvidenceError, match="absent or a regular file"):
        write_release_manifest({"schema_version": 1}, destination)

    assert destination.is_dir()


def test_write_release_manifest_bounds_temporary_creation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convert non-collision temporary creation failures to a fixed error."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    original_open = release_evidence.os.open

    def failing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fsdecode(path) == f".{_MANIFEST_NAME}.tmp":
            raise PermissionError("untrusted temporary error")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(release_evidence.os, "open", failing_open)

    with pytest.raises(ReleaseEvidenceError, match="temporary file could not be created"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not destination.exists()


def test_write_release_manifest_closes_temporary_descriptor_after_fdopen_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close and unlink the owned temporary when text-stream creation fails."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    temporary = destination.parent / f".{_MANIFEST_NAME}.tmp"
    captured_descriptors: list[int] = []

    def failing_fdopen(descriptor: int, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        captured_descriptors.append(descriptor)
        raise OSError("untrusted fdopen error")

    monkeypatch.setattr(release_evidence.os, "fdopen", failing_fdopen)

    with pytest.raises(ReleaseEvidenceError, match="manifest write failed"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not temporary.exists()
    with pytest.raises(OSError):
        os.fstat(captured_descriptors[0])


def test_write_release_manifest_cleans_temporary_after_file_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove the owned temporary when manifest-byte synchronization fails."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    temporary = destination.parent / f".{_MANIFEST_NAME}.tmp"
    original_fsync = release_evidence.os.fsync

    def failing_file_fsync(descriptor: int) -> None:
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("untrusted file sync error")
        original_fsync(descriptor)

    monkeypatch.setattr(release_evidence.os, "fsync", failing_file_fsync)

    with pytest.raises(ReleaseEvidenceError, match="manifest write failed"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not destination.exists()
    assert not temporary.exists()


def test_write_release_manifest_cleans_owned_temporary_after_rename_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove only this invocation's temporary file when atomic replacement fails."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    destination.parent.mkdir()
    destination.write_text("trusted predecessor", encoding="utf-8")
    temporary = destination.parent / f".{_MANIFEST_NAME}.tmp"

    def fail_rename(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("untrusted replacement error")

    monkeypatch.setattr(release_evidence.os, "rename", fail_rename)

    with pytest.raises(ReleaseEvidenceError, match="atomic replacement failed"):
        write_release_manifest({"schema_version": 1}, destination)

    assert destination.read_text(encoding="utf-8") == "trusted predecessor"
    assert not temporary.exists()


def test_write_release_manifest_tolerates_missing_owned_temporary_during_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the primary replacement error when the temporary is already absent."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME

    def remove_then_fail(
        source: str,
        target: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        del target, dst_dir_fd
        os.unlink(source, dir_fd=src_dir_fd)
        raise OSError("untrusted replacement error")

    monkeypatch.setattr(release_evidence.os, "rename", remove_then_fail)

    with pytest.raises(ReleaseEvidenceError, match="atomic replacement failed"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not destination.exists()


def test_write_release_manifest_reports_owned_temporary_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when the current invocation's temporary cannot be removed."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    temporary = destination.parent / f".{_MANIFEST_NAME}.tmp"

    def fail_rename(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("untrusted replacement error")

    def fail_unlink(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise PermissionError("untrusted cleanup error")

    monkeypatch.setattr(release_evidence.os, "rename", fail_rename)
    monkeypatch.setattr(release_evidence.os, "unlink", fail_unlink)

    with pytest.raises(ReleaseEvidenceError, match="temporary cleanup failed"):
        write_release_manifest({"schema_version": 1}, destination)

    assert temporary.exists()


def test_write_release_manifest_reports_parent_directory_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report a durable-directory failure after the atomic replacement succeeds."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    temporary = destination.parent / f".{_MANIFEST_NAME}.tmp"
    original_fsync = release_evidence.os.fsync

    def failing_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("untrusted directory sync error")
        original_fsync(descriptor)

    monkeypatch.setattr(release_evidence.os, "fsync", failing_directory_fsync)

    with pytest.raises(ReleaseEvidenceError, match="directory synchronization failed"):
        write_release_manifest({"schema_version": 1}, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == {"schema_version": 1}
    assert not temporary.exists()


def test_write_release_manifest_synchronizes_file_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synchronize both manifest bytes and the directory entry replacement."""
    destination = tmp_path / "evidence" / _MANIFEST_NAME
    synchronized_modes: list[int] = []
    original_fsync = release_evidence.os.fsync

    def recording_fsync(descriptor: int) -> None:
        synchronized_modes.append(os.fstat(descriptor).st_mode)
        original_fsync(descriptor)

    monkeypatch.setattr(release_evidence.os, "fsync", recording_fsync)

    write_release_manifest({"schema_version": 1}, destination)

    assert len(synchronized_modes) == 2
    assert stat.S_ISREG(synchronized_modes[0])
    assert stat.S_ISDIR(synchronized_modes[1])
