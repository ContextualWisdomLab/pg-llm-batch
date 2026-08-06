# SPDX-License-Identifier: Apache-2.0
"""Security regressions for descriptor-pinned release artifact verification."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import pg_llm_batch.release_evidence as release_evidence
from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


DISTRIBUTION = "pg-llm-batch"
VERSION = "0.1.0"
COMMIT = "a" * 40
SOURCE_DATE_EPOCH = 1_786_000_000
WHEEL = "pg_llm_batch-0.1.0-py3-none-any.whl"
SDIST = "pg_llm_batch-0.1.0.tar.gz"


def _write_release(directory: Path) -> None:
    """Create one deterministic wheel and source distribution fixture."""
    directory.mkdir(parents=True)
    (directory / WHEEL).write_bytes(b"wheel")
    (directory / SDIST).write_bytes(b"sdist")


def _verify(first: Path, second: Path) -> dict[str, object]:
    """Verify two fixtures through the public release evidence contract."""
    return verify_reproducible_release(  # type: ignore[return-value]
        first,
        second,
        distribution_name=DISTRIBUTION,
        version=VERSION,
        source_commit=COMMIT,
        source_date_epoch=SOURCE_DATE_EPOCH,
    )


def test_verifier_refuses_symlinked_parent_component(tmp_path: Path) -> None:
    """Reject a parent-path redirect rather than only checking the final directory."""
    outside = tmp_path / "outside"
    first = outside / "first"
    second = outside / "second"
    _write_release(first)
    _write_release(second)
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ReleaseEvidenceError, match="parent.*symlink|directory path"):
        _verify(linked / "first", linked / "second")


def test_verifier_refuses_artifact_replacement_after_directory_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not follow a symlink installed after bounded name enumeration."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    outside = tmp_path / "outside.whl"
    outside.write_bytes(b"other")
    target = first / WHEEL
    original = first / "original.whl"
    swapped = False
    original_path_open = Path.open
    original_os_open = os.open

    def swap_target() -> None:
        nonlocal swapped
        if swapped:
            return
        swapped = True
        target.rename(original)
        target.symlink_to(outside)

    def racing_path_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path == target:
            swap_target()
        return original_path_open(path, *args, **kwargs)

    def racing_os_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and os.fspath(path) == WHEEL:
            swap_target()
        return original_os_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "open", racing_path_open)
    monkeypatch.setattr(os, "open", racing_os_open)

    with pytest.raises(
        ReleaseEvidenceError,
        match="regular non-symlink|changed during verification",
    ):
        _verify(first, second)


def test_verifier_refuses_directory_entry_change_after_initial_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revalidate the bounded directory identity after artifact reads complete."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    unexpected = first / "unexpected.txt"
    mutated = False
    original_path_open = Path.open
    original_os_open = os.open

    def add_entry() -> None:
        nonlocal mutated
        if mutated:
            return
        mutated = True
        unexpected.write_bytes(b"extra")

    def racing_path_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if path == first / SDIST:
            add_entry()
        return original_path_open(path, *args, **kwargs)

    def racing_os_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and os.fspath(path) == SDIST:
            add_entry()
        return original_os_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "open", racing_path_open)
    monkeypatch.setattr(os, "open", racing_os_open)

    with pytest.raises(
        ReleaseEvidenceError,
        match="changed during verification|exactly one wheel and one sdist",
    ):
        _verify(first, second)


def test_verifier_refuses_in_place_mutation_during_streaming_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject bytes read from an artifact whose inode metadata changes mid-read."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    original_read = os.read
    mutated = False

    def racing_read(file_descriptor: int, count: int) -> bytes:
        nonlocal mutated
        chunk = original_read(file_descriptor, count)
        if chunk and not mutated:
            mutated = True
            (first / SDIST).write_bytes(b"other")
        return chunk

    monkeypatch.setattr(os, "read", racing_read)

    with pytest.raises(ReleaseEvidenceError, match="changed during verification"):
        _verify(first, second)


def test_verifier_fails_closed_without_secure_artifact_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require descriptor-relative no-follow support before reading artifacts."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    monkeypatch.setattr(
        release_evidence,
        "_SECURE_ARTIFACT_FLAGS_AVAILABLE",
        False,
        raising=False,
    )

    with pytest.raises(
        ReleaseEvidenceError,
        match="secure release artifact verification requires descriptor-relative no-follow support",
    ):
        _verify(first, second)
