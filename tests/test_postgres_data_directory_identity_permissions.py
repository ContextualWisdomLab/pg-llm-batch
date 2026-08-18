# SPDX-License-Identifier: Apache-2.0
"""Permission-boundary regressions for PostgreSQL data-directory identity."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_data_directory_identity import (
    PostgresDataDirectoryIdentityError,
    verify_postgres_data_directory_identity,
)
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


_SYSTEM_IDENTIFIER = 7_394_886_517_812_345_678
_INVALID_INPUT = "^invalid PostgreSQL data-directory identity inputs$"


def _open_directory(path: Path, mode: int) -> int:
    """Create and open one directory with an exact post-umask mode."""
    path.mkdir()
    os.chmod(path, mode)
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _open_control_script(tmp_path: Path, mode: int) -> int:
    """Create and open one executable pg_controldata fixture."""
    script = tmp_path / f"pg_controldata-{mode:o}"
    script.write_text(
        "#!/bin/sh\nprintf 'Database system identifier: "
        f"{_SYSTEM_IDENTIFIER}\\n'\n",
        encoding="utf-8",
    )
    os.chmod(script, mode)
    return os.open(script, os.O_RDONLY)


def _expected_identity() -> PostgresRestoreTargetIdentity:
    """Return the exact restore-target identity used by this regression."""
    return PostgresRestoreTargetIdentity(system_identifier=_SYSTEM_IDENTIFIER)


def _forbidden_subprocess(*_args: object, **_kwargs: object) -> NoReturn:
    """Fail if unsafe filesystem authority reaches child execution."""
    raise AssertionError("unsafe recovery authority must fail before pg_controldata")


@pytest.mark.parametrize("mode", [0o770, 0o707])
def test_verifier_rejects_group_or_other_writable_data_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
) -> None:
    """A different local principal must not be able to rewrite inspected cluster state."""
    data_fd = _open_directory(tmp_path / f"restore-data-{mode:o}", mode)
    control_fd = _open_control_script(tmp_path, 0o755)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresDataDirectoryIdentityError, match=_INVALID_INPUT):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(control_fd)
        os.close(data_fd)


@pytest.mark.parametrize("mode", [0o720, 0o702])
def test_verifier_rejects_group_or_other_writable_control_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
) -> None:
    """A mutable trusted executable capability must fail before child execution."""
    data_fd = _open_directory(tmp_path / f"restore-data-{mode:o}", 0o750)
    control_fd = _open_control_script(tmp_path, mode)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresDataDirectoryIdentityError, match=_INVALID_INPUT):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(control_fd)
        os.close(data_fd)


def test_verifier_allows_group_read_search_without_group_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PostgreSQL-compatible shared read/search permission remains supported."""
    data_fd = _open_directory(tmp_path / "restore-data-read-search", 0o750)
    control_fd = _open_control_script(tmp_path, 0o755)

    def successful_run(
        arguments: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=(
                f"Database system identifier: {_SYSTEM_IDENTIFIER}\n".encode("ascii")
            ),
        )

    monkeypatch.setattr(subprocess, "run", successful_run)
    try:
        verify_postgres_data_directory_identity(
            data_directory_fd=data_fd,
            pg_controldata_fd=control_fd,
            expected_identity=_expected_identity(),
        )
    finally:
        os.close(control_fd)
        os.close(data_fd)
