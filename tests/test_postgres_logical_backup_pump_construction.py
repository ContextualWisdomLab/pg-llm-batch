# SPDX-License-Identifier: Apache-2.0
"""Regression tests for logical-backup output-pump construction failures."""

from __future__ import annotations

import os

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)
from tests.logical_backup_test_support import install_retained_pg_dump_stub


pytestmark = pytest.mark.usefixtures(install_retained_pg_dump_stub.__name__)


def test_logical_backup_closes_pipe_when_output_pump_construction_fails(
    tmp_path, monkeypatch
):
    path = tmp_path / "backup.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    real_pipe = os.pipe
    pipe_descriptors: list[int] = []

    def recording_pipe():
        read_descriptor, write_descriptor = real_pipe()
        pipe_descriptors.extend((read_descriptor, write_descriptor))
        return read_descriptor, write_descriptor

    class ConstructorFailureThread:
        def __init__(self, **_kwargs):
            raise RuntimeError("private constructor detail")

    monkeypatch.setattr(logical_backup.os, "pipe", recording_pipe)
    monkeypatch.setattr(logical_backup.threading, "Thread", ConstructorFailureThread)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("provider must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup execution failed$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "private" not in str(caught.value)
        assert len(pipe_descriptors) == 2
        for pipe_descriptor in pipe_descriptors:
            with pytest.raises(OSError):
                os.fstat(pipe_descriptor)
        assert os.fstat(descriptor).st_size == 0
    finally:
        for pipe_descriptor in pipe_descriptors:
            try:
                os.close(pipe_descriptor)
            except OSError:
                pass
        os.close(descriptor)
