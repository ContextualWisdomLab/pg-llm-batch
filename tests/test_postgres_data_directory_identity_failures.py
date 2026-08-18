# SPDX-License-Identifier: Apache-2.0
"""Focused failure-path coverage for PostgreSQL data-directory identity checks."""

from __future__ import annotations

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
