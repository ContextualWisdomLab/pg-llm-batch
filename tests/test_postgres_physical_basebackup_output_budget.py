# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for finite physical base-backup output volume."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import (
    PostgresPhysicalBaseBackupError,
    PostgresPhysicalBaseBackupResult,
    create_postgres_physical_basebackup,
)


@pytest.fixture(autouse=True)
def _retain_hermetic_test_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep output-budget tests independent of host PostgreSQL packaging."""
    monkeypatch.setattr(
        physical_basebackup,
        "_retain_pg_basebackup_executable",
        lambda _path: os.open(os.devnull, os.O_RDONLY),
    )


def _open_private_output(tmp_path: Path, name: str) -> tuple[Path, int]:
    """Create one caller-owned private empty backup target."""
    path = tmp_path / name
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


def test_physical_backup_accepts_exact_output_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backup that ends exactly at the configured byte ceiling must succeed."""
    path, descriptor = _open_private_output(tmp_path, "exact-budget.tar")
    payload = b"bounded-physical-backup"

    def exact_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        stdout = kwargs["stdout"]
        assert type(stdout) is int
        os.write(stdout, payload)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", exact_run)
    try:
        result = create_postgres_physical_basebackup(
            "physical_backup_source",
            descriptor,
            pg_basebackup_executable="/usr/bin/pg_basebackup",
            maximum_output_bytes=len(payload),
        )
        assert result == PostgresPhysicalBaseBackupResult(size_bytes=len(payload))
        assert path.read_bytes() == payload
    finally:
        os.close(descriptor)


def test_physical_backup_rejects_one_byte_over_budget_and_invalidates_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading one byte beyond the ceiling must fail closed without retaining bytes."""
    path, descriptor = _open_private_output(tmp_path, "over-budget.tar")
    payload = b"12345"

    def oversized_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        stdout = kwargs["stdout"]
        assert type(stdout) is int
        os.write(stdout, payload)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", oversized_run)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base backup exceeded output byte budget$",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
                maximum_output_bytes=len(payload) - 1,
            )
        assert path.read_bytes() == b""
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
    finally:
        os.close(descriptor)


def test_over_budget_stream_stops_a_continuing_producer_and_reaps_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing the bounded pipe must release a producer that keeps writing."""
    path, descriptor = _open_private_output(tmp_path, "continuing-producer.tar")
    producer_stopped = False

    def continuing_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal producer_stopped
        stdout = kwargs["stdout"]
        assert type(stdout) is int
        try:
            while True:
                os.write(stdout, b"x" * 65_536)
        except BrokenPipeError:
            producer_stopped = True
            return subprocess.CompletedProcess(arguments, 1)

    monkeypatch.setattr(subprocess, "run", continuing_run)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base backup exceeded output byte budget$",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
                maximum_output_bytes=1024,
            )
        assert producer_stopped is True
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)


def test_final_output_cannot_exceed_budget_through_caller_fd_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent caller writes cannot make a successful result exceed the ceiling."""
    path, descriptor = _open_private_output(tmp_path, "caller-expanded.tar")
    provider_payload = b"provider"
    maximum_output_bytes = len(provider_payload)

    def caller_expands_output(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        stdout = kwargs["stdout"]
        assert type(stdout) is int
        os.write(stdout, provider_payload)
        os.pwrite(descriptor, b"x", maximum_output_bytes + 1)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", caller_expands_output)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base backup exceeded output byte budget$",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
                maximum_output_bytes=maximum_output_bytes,
            )
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("invalid_budget", [True, 0, -1, 1 << 63])
def test_invalid_output_budget_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_budget: object,
) -> None:
    """The output ceiling must be an exact positive signed-bigint-sized integer."""
    _path, descriptor = _open_private_output(tmp_path, "invalid-budget.tar")

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("invalid output budget must not execute pg_basebackup")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^invalid PostgreSQL physical base-backup parameters$",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
                maximum_output_bytes=invalid_budget,  # type: ignore[arg-type]
            )
    finally:
        os.close(descriptor)
