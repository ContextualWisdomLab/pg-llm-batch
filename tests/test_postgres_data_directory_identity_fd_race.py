# SPDX-License-Identifier: Apache-2.0
"""Regressions for descriptor replacement during PostgreSQL identity inspection."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from pg_llm_batch.postgres_data_directory_identity import (
    PostgresDataDirectoryIdentityError,
    verify_postgres_data_directory_identity,
)
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


_SYSTEM_IDENTIFIER = 7_394_886_517_812_345_678
_CONTROL_IDENTITIES: set[tuple[int, int]] = set()


def _open_directory(path: Path) -> int:
    """Open one caller-owned directory capability."""
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _with_owner(status: os.stat_result, user_id: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit owner identity."""
    fields = list(status)
    fields[4] = user_id
    return os.stat_result(fields)


@pytest.fixture(autouse=True)
def _model_root_owned_control_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Model temporary control scripts as trusted root-owned system tools."""
    _CONTROL_IDENTITIES.clear()
    real_fstat = os.fstat

    def root_owned_control_metadata(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) in _CONTROL_IDENTITIES:
            return _with_owner(status, 0)
        return status

    monkeypatch.setattr(os, "fstat", root_owned_control_metadata)
    yield
    _CONTROL_IDENTITIES.clear()


def _open_control_script(path: Path, system_identifier: int) -> int:
    """Open and register one root-owned control-tool fixture capability."""
    path.write_text(
        "#!/bin/sh\n"
        f"printf 'Database system identifier:           {system_identifier}\\n'\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    file_descriptor = os.open(path, os.O_RDONLY)
    status = os.fstat(file_descriptor)
    _CONTROL_IDENTITIES.add((status.st_dev, status.st_ino))
    return file_descriptor


def test_verifier_snapshots_control_fd_before_subprocess_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing the caller FD after validation must not replace the trusted tool."""
    trusted_fd = _open_control_script(
        tmp_path / "trusted-pg-controldata", _SYSTEM_IDENTIFIER - 1
    )
    replacement_fd = _open_control_script(
        tmp_path / "replacement-pg-controldata", _SYSTEM_IDENTIFIER
    )
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    real_run = subprocess.run

    def replace_caller_fd_then_run(
        args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        os.dup2(replacement_fd, trusted_fd)
        return real_run(args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", replace_caller_fd_then_run)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^PostgreSQL data directory does not match restore target identity$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=trusted_fd,
                expected_identity=PostgresRestoreTargetIdentity(
                    system_identifier=_SYSTEM_IDENTIFIER
                ),
            )
    finally:
        os.close(data_directory_fd)
        os.close(replacement_fd)
        os.close(trusted_fd)


@pytest.mark.parametrize("failed_duplication", [1, 2])
def test_verifier_fails_closed_and_cleans_snapshots_when_duplication_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_duplication: int,
) -> None:
    """Map descriptor-snapshot failures to fixed diagnostics without leaking FDs."""
    control_fd = _open_control_script(
        tmp_path / "pg-controldata", _SYSTEM_IDENTIFIER
    )
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    real_dup = os.dup
    duplication_count = 0
    snapshots: list[int] = []

    def controlled_dup(file_descriptor: int) -> int:
        nonlocal duplication_count
        duplication_count += 1
        if duplication_count == failed_duplication:
            raise OSError("sensitive descriptor duplication diagnostic")
        snapshot = real_dup(file_descriptor)
        snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr(os, "dup", controlled_dup)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=PostgresRestoreTargetIdentity(
                    system_identifier=_SYSTEM_IDENTIFIER
                ),
            )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)

    assert duplication_count == failed_duplication
    for snapshot in snapshots:
        with pytest.raises(OSError):
            os.fstat(snapshot)
