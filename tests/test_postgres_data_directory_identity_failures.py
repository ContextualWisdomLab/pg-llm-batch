# SPDX-License-Identifier: Apache-2.0
"""Focused failure-path coverage for PostgreSQL data-directory identity checks."""

from __future__ import annotations

import stat
import subprocess
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_data_directory_identity as data_directory_identity
from pg_llm_batch.postgres_data_directory_identity import (
    PostgresDataDirectoryIdentityError,
    verify_postgres_data_directory_identity,
)
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


def test_descriptor_inspection_oserror_maps_to_content_free_input_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Map descriptor inspection failure to the fixed invalid-input boundary."""

    def fail_fstat(file_descriptor: int) -> object:
        raise OSError(f"sensitive descriptor diagnostic for {file_descriptor}")

    monkeypatch.setattr(data_directory_identity.os, "fstat", fail_fstat)

    with pytest.raises(
        PostgresDataDirectoryIdentityError,
        match="^invalid PostgreSQL data-directory identity inputs$",
    ):
        verify_postgres_data_directory_identity(
            data_directory_fd=3,
            pg_controldata_fd=4,
            expected_identity=PostgresRestoreTargetIdentity(system_identifier=1),
        )


@pytest.mark.parametrize("failing_descriptor", [100, 101])
def test_package_owned_snapshot_close_failure_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    failing_descriptor: int,
) -> None:
    """Do not leak or replace a verified result when private snapshot close fails."""
    duplicate_descriptors = iter((100, 101))
    close_attempts: list[int] = []

    monkeypatch.setattr(
        data_directory_identity.os,
        "dup",
        lambda file_descriptor: next(duplicate_descriptors),
    )

    def fake_fstat(file_descriptor: int) -> object:
        owner_id = data_directory_identity.os.geteuid()
        if file_descriptor == 100:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=owner_id)
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o700, st_uid=owner_id)

    monkeypatch.setattr(data_directory_identity.os, "fstat", fake_fstat)
    monkeypatch.setattr(
        data_directory_identity.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=b"Database system identifier: 1\n",
        ),
    )

    def close_snapshot(file_descriptor: int) -> None:
        close_attempts.append(file_descriptor)
        if file_descriptor == failing_descriptor:
            raise OSError("sensitive private-descriptor close diagnostic")

    monkeypatch.setattr(data_directory_identity.os, "close", close_snapshot)

    verify_postgres_data_directory_identity(
        data_directory_fd=3,
        pg_controldata_fd=4,
        expected_identity=PostgresRestoreTargetIdentity(system_identifier=1),
    )

    assert close_attempts == [101, 100]
