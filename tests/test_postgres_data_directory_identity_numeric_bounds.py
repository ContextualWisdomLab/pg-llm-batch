# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for bounded PostgreSQL system-identifier parsing."""

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


def test_oversized_decimal_identifier_uses_content_free_package_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject huge decimal output before interpreter integer parsing can escape."""
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = os.open(data_directory, os.O_RDONLY | os.O_DIRECTORY)

    control_script = tmp_path / "pg_controldata-fixture"
    control_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    control_script.chmod(0o700)
    control_fd = os.open(control_script, os.O_RDONLY)
    real_fstat = os.fstat
    control_status = real_fstat(control_fd)
    control_identity = (control_status.st_dev, control_status.st_ino)

    def root_owned_control_metadata(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) == control_identity:
            fields = list(status)
            fields[4] = 0
            return os.stat_result(fields)
        return status

    monkeypatch.setattr(os, "fstat", root_owned_control_metadata)
    output = b"Database system identifier: " + (b"9" * 5_000) + b"\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=output),
    )

    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^could not inspect PostgreSQL data-directory identity$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=PostgresRestoreTargetIdentity(system_identifier=1),
            )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)
