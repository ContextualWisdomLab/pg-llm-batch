# SPDX-License-Identifier: Apache-2.0
"""Regress caller descriptor substitution during PostgreSQL logical restore."""

from __future__ import annotations

import os
import subprocess

import pg_llm_batch.postgres_logical_restore as logical_restore
from pg_llm_batch.postgres_logical_restore import (
    PostgresLogicalRestoreResult,
    restore_postgres_logical_backup,
)


def _open_private_archive(tmp_path, name: str, payload: bytes) -> int:
    """Create one private regular archive descriptor positioned at byte zero."""
    descriptor = os.open(
        tmp_path / name,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    os.write(descriptor, payload)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor


def test_restore_retains_inspected_archive_when_caller_replaces_descriptor(
    tmp_path, monkeypatch
):
    """Keep child authority on inspected bytes across caller-side ``dup2`` replacement."""
    original_payload = b"PGDMP-original"
    replacement_payload = b"PGDMP-replaced"
    caller_descriptor = _open_private_archive(
        tmp_path,
        "original.dump",
        original_payload,
    )
    replacement_descriptor = _open_private_archive(
        tmp_path,
        "replacement.dump",
        replacement_payload,
    )
    consumed_payloads: list[bytes] = []

    def replace_caller_descriptor_then_run(argv, **kwargs):
        os.dup2(replacement_descriptor, caller_descriptor)
        child_descriptor = kwargs["stdin"]
        os.lseek(child_descriptor, 0, os.SEEK_SET)
        consumed_payloads.append(os.read(child_descriptor, len(original_payload)))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        replace_caller_descriptor_then_run,
    )
    try:
        result = restore_postgres_logical_backup(
            "isolated_restore",
            caller_descriptor,
            source_superusers_trusted=True,
            pg_restore_executable="/usr/bin/pg_restore",
        )
        assert result == PostgresLogicalRestoreResult(size_bytes=len(original_payload))
        assert consumed_payloads == [original_payload]
    finally:
        os.close(caller_descriptor)
        os.close(replacement_descriptor)
