# SPDX-License-Identifier: Apache-2.0
"""Filesystem-capacity regressions for bounded PostgreSQL WAL reception."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_wal_archive as wal_archive
from pg_llm_batch.postgres_wal_archive import PostgresWalArchiveError


_GIB = 1024 * 1024 * 1024


def _open_private_directory(tmp_path: Path, name: str) -> int:
    """Create one owner-only empty archive directory and return its descriptor."""
    path = tmp_path / name
    path.mkdir(mode=0o700)
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


@pytest.mark.parametrize("budget", (True, 0, -1, 1024**4 + 1))
def test_invalid_archive_byte_budget_fails_before_authority_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget: object,
) -> None:
    """Only an exact positive finite aggregate byte budget may reach filesystem I/O."""
    descriptor = _open_private_directory(tmp_path, "invalid-budget")

    def forbidden_dup(_descriptor: int) -> NoReturn:
        raise AssertionError("invalid byte budgets must fail before descriptor retention")

    monkeypatch.setattr(os, "dup", forbidden_dup)
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="^invalid PostgreSQL WAL archive parameters$",
        ):
            wal_archive.receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
                maximum_archive_bytes=budget,  # type: ignore[arg-type]
            )
    finally:
        os.close(descriptor)


def test_receive_rejects_shared_filesystem_before_executable_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared filesystem must fail before executable authority or provider execution."""
    descriptor = _open_private_directory(tmp_path, "shared-receive-filesystem")
    retained_descriptors: list[int] = []
    real_dup = os.dup
    real_close = os.close

    def tracking_dup(source_descriptor: int) -> int:
        retained_descriptor = real_dup(source_descriptor)
        retained_descriptors.append(retained_descriptor)
        return retained_descriptor

    def forbidden_executable(_pg_receivewal_executable: str) -> NoReturn:
        raise AssertionError(
            "filesystem budget must fail before executable retention"
        )

    monkeypatch.setattr(os, "dup", tracking_dup)
    monkeypatch.setattr(
        wal_archive,
        "_retain_pg_receivewal_executable",
        forbidden_executable,
    )
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="isolated bounded filesystem",
        ):
            wal_archive.receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
                maximum_archive_bytes=64 * _GIB,
            )
        assert retained_descriptors
        for retained_descriptor in retained_descriptors:
            with pytest.raises(OSError):
                os.fstat(retained_descriptor)
    finally:
        real_close(descriptor)


def test_archive_budget_requires_distinct_filesystem_root(tmp_path: Path) -> None:
    """A shared host filesystem cannot act as the receiver's aggregate byte quota."""
    descriptor = _open_private_directory(tmp_path, "shared-filesystem")
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="isolated bounded filesystem",
        ):
            wal_archive._inspect_archive_filesystem_budget(descriptor, 64 * _GIB)
    finally:
        os.close(descriptor)


def test_archive_budget_accepts_distinct_filesystem_within_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distinct mount whose total data-block capacity fits the budget is accepted."""
    descriptor = _open_private_directory(tmp_path, "bounded-filesystem")
    current_device = os.fstat(descriptor).st_dev
    real_stat = os.stat

    def distinct_parent(path: object, *args: object, **kwargs: object) -> object:
        if path == ".." and kwargs.get("dir_fd") == descriptor:
            return SimpleNamespace(st_dev=current_device + 1)
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", distinct_parent)
    monkeypatch.setattr(
        os,
        "fstatvfs",
        lambda _descriptor: SimpleNamespace(f_frsize=4096, f_blocks=262_144),
    )
    try:
        assert wal_archive._inspect_archive_filesystem_budget(
            descriptor,
            2 * _GIB,
        ) == _GIB
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("fragment_size", "block_count"),
    (
        (True, 262_144),
        (0, 262_144),
        (4096, True),
        (4096, -1),
    ),
)
def test_archive_budget_rejects_invalid_filesystem_capacity_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fragment_size: object,
    block_count: object,
) -> None:
    """Malformed filesystem-capacity authority fails through one fixed boundary."""
    descriptor = _open_private_directory(tmp_path, "invalid-filesystem-capacity")
    current_device = os.fstat(descriptor).st_dev
    real_stat = os.stat

    def distinct_parent(path: object, *args: object, **kwargs: object) -> object:
        if path == ".." and kwargs.get("dir_fd") == descriptor:
            return SimpleNamespace(st_dev=current_device + 1)
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", distinct_parent)
    monkeypatch.setattr(
        os,
        "fstatvfs",
        lambda _descriptor: SimpleNamespace(
            f_frsize=fragment_size,
            f_blocks=block_count,
        ),
    )
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="filesystem budget could not be inspected",
        ) as caught:
            wal_archive._inspect_archive_filesystem_budget(descriptor, 2 * _GIB)
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__ is True
    finally:
        os.close(descriptor)


def test_archive_budget_rejects_filesystem_capacity_above_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kernel-backed filesystem capacity may not exceed the caller's byte ceiling."""
    descriptor = _open_private_directory(tmp_path, "oversized-filesystem")
    current_device = os.fstat(descriptor).st_dev
    real_stat = os.stat

    def distinct_parent(path: object, *args: object, **kwargs: object) -> object:
        if path == ".." and kwargs.get("dir_fd") == descriptor:
            return SimpleNamespace(st_dev=current_device + 1)
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", distinct_parent)
    monkeypatch.setattr(
        os,
        "fstatvfs",
        lambda _descriptor: SimpleNamespace(f_frsize=4096, f_blocks=524_288),
    )
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="exceeds configured byte budget",
        ):
            wal_archive._inspect_archive_filesystem_budget(descriptor, _GIB)
    finally:
        os.close(descriptor)


def test_archive_budget_inspection_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filesystem-capacity diagnostics cannot disclose host storage details."""
    descriptor = _open_private_directory(tmp_path, "failed-filesystem-inspection")

    def broken_statvfs(_descriptor: int) -> NoReturn:
        raise OSError("SECRET-SENTINEL volume path and capacity")

    monkeypatch.setattr(os, "fstatvfs", broken_statvfs)
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="filesystem budget could not be inspected",
        ) as caught:
            wal_archive._inspect_archive_filesystem_budget(descriptor, _GIB)
        assert "SECRET-SENTINEL" not in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__ is True
    finally:
        os.close(descriptor)
