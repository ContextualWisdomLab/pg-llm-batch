# SPDX-License-Identifier: Apache-2.0
"""Security regressions for descriptor-bound release manifest writes."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import pg_llm_batch.release_evidence as release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, write_release_manifest


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
    destination = evidence / "release-manifest.json"
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
        if not swapped and path_text.endswith(".release-manifest.json.tmp"):
            evidence.rename(held_evidence)
            evidence.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(release_evidence.os, "open", swapping_open)

    write_release_manifest({"schema_version": 1}, destination)

    assert swapped
    assert not (outside / "release-manifest.json").exists()
    assert json.loads(
        (held_evidence / "release-manifest.json").read_text(encoding="utf-8")
    ) == {"schema_version": 1}


def test_write_release_manifest_fails_without_secure_dir_fd_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail before mutation when descriptor-relative no-follow writes are unavailable."""
    destination = tmp_path / "evidence" / "release-manifest.json"
    monkeypatch.setattr(release_evidence.os, "supports_dir_fd", set())

    with pytest.raises(ReleaseEvidenceError, match="descriptor-relative no-follow"):
        write_release_manifest({"schema_version": 1}, destination)

    assert not destination.parent.exists()


def test_write_release_manifest_cleans_owned_temporary_after_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove only this invocation's temporary file when atomic replacement fails."""
    destination = tmp_path / "evidence" / "release-manifest.json"
    destination.parent.mkdir()
    destination.write_text("trusted predecessor", encoding="utf-8")
    temporary = destination.parent / ".release-manifest.json.tmp"

    def fail_replace(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(release_evidence.os, "replace", fail_replace)

    with pytest.raises(ReleaseEvidenceError, match="replace"):
        write_release_manifest({"schema_version": 1}, destination)

    assert destination.read_text(encoding="utf-8") == "trusted predecessor"
    assert not temporary.exists()


def test_write_release_manifest_synchronizes_file_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synchronize both manifest bytes and the directory entry replacement."""
    destination = tmp_path / "evidence" / "release-manifest.json"
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


def test_write_release_manifest_rejects_parent_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a relative parent component instead of escaping the selected directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    escaped = tmp_path / "release-manifest.json"

    with pytest.raises(ReleaseEvidenceError, match="parent traversal"):
        write_release_manifest(
            {"schema_version": 1},
            Path("..") / "release-manifest.json",
        )

    assert not escaped.exists()
