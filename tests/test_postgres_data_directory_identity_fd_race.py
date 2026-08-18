# SPDX-License-Identifier: Apache-2.0
"""Regression test for descriptor-number replacement during identity inspection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pg_llm_batch.postgres_data_directory_identity import (
    PostgresDataDirectoryIdentityError,
    verify_postgres_data_directory_identity,
)
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


_SYSTEM_IDENTIFIER = 7_394_886_517_812_345_678


def _open_directory(path: Path) -> int:
    """Open one caller-owned directory capability."""
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _open_control_script(path: Path, system_identifier: int) -> int:
    """Open one executable control-tool fixture capability."""
    path.write_text(
        "#!/bin/sh\n"
        f"printf 'Database system identifier:           {system_identifier}\\n'\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return os.open(path, os.O_RDONLY)


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
