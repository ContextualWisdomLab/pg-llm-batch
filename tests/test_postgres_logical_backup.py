# SPDX-License-Identifier: Apache-2.0
"""Regression tests for bounded PostgreSQL logical backup execution."""

from __future__ import annotations

import os
import stat
import subprocess
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    PostgresLogicalBackupResult,
    create_postgres_logical_backup,
)


def _open_private_output(tmp_path):
    path = tmp_path / "backup.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    return path, descriptor


def _write_successfully(argv, **kwargs):
    os.write(kwargs["stdout"], b"PGDMP\x01\x02\x03")
    return subprocess.CompletedProcess(argv, 0)


def _read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    return os.read(descriptor, 1024)


def test_logical_backup_uses_bounded_content_free_subprocess_contract(
    tmp_path, monkeypatch
):
    path, descriptor = _open_private_output(tmp_path)
    observed = {}

    monkeypatch.setenv("PGSERVICEFILE", "/run/secrets/pg_service.conf")
    monkeypatch.setenv("PGPASSWORD", "credential-value")
    monkeypatch.setenv("PGPASSFILE", "/run/secrets/pgpass")
    monkeypatch.setenv("PGHOST", "attacker-controlled-host")
    monkeypatch.setenv("PGDATABASE", "attacker-controlled-database")
    monkeypatch.setenv("PGOPTIONS", "-c search_path=attacker")
    monkeypatch.setenv("PGSSLMODE", "disable")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "must-not-reach-pg-dump")

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return _write_successfully(argv, **kwargs)

    monkeypatch.setattr(logical_backup.subprocess, "run", fake_run)
    try:
        result = create_postgres_logical_backup(
            "tenant_backup",
            descriptor,
            pg_dump_executable="/usr/lib/postgresql/18/bin/pg_dump",
            timeout_seconds=31,
            connect_timeout_seconds=7,
        )
        assert result == PostgresLogicalBackupResult(size_bytes=8)
        assert observed["argv"] == [
            "/usr/lib/postgresql/18/bin/pg_dump",
            "--format=custom",
            "--no-password",
        ]
        assert observed["kwargs"]["stdout"] == descriptor
        assert observed["kwargs"]["stderr"] is subprocess.DEVNULL
        assert observed["kwargs"]["stdin"] is subprocess.DEVNULL
        assert observed["kwargs"]["timeout"] == 31
        assert observed["kwargs"]["check"] is False
        assert observed["kwargs"]["close_fds"] is True
        assert observed["kwargs"]["env"] == {
            "PGSERVICEFILE": "/run/secrets/pg_service.conf",
            "PGPASSWORD": "credential-value",
            "PGPASSFILE": "/run/secrets/pgpass",
            "PGSERVICE": "tenant_backup",
            "PGCONNECT_TIMEOUT": "7",
        }
        assert str(path) not in " ".join(observed["argv"])
        assert "tenant_backup" not in " ".join(observed["argv"])
        assert _read_descriptor(descriptor) == b"PGDMP\x01\x02\x03"
        os.fstat(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"service_name": ""}, "invalid PostgreSQL logical backup parameters"),
        ({"service_name": "bad service"}, "invalid PostgreSQL logical backup parameters"),
        ({"service_name": type("Text", (str,), {})("safe")}, "invalid PostgreSQL logical backup parameters"),
        ({"output_descriptor": True}, "invalid PostgreSQL logical backup parameters"),
        ({"output_descriptor": -1}, "invalid PostgreSQL logical backup parameters"),
        ({"pg_dump_executable": "pg_dump"}, "invalid PostgreSQL logical backup parameters"),
        ({"pg_dump_executable": "/usr/bin/not-pg-dump"}, "invalid PostgreSQL logical backup parameters"),
        ({"pg_dump_executable": type("Text", (str,), {})("/usr/bin/pg_dump")}, "invalid PostgreSQL logical backup parameters"),
        ({"timeout_seconds": 0}, "invalid PostgreSQL logical backup parameters"),
        ({"timeout_seconds": True}, "invalid PostgreSQL logical backup parameters"),
        ({"timeout_seconds": 86401}, "invalid PostgreSQL logical backup parameters"),
        ({"connect_timeout_seconds": 0}, "invalid PostgreSQL logical backup parameters"),
        ({"connect_timeout_seconds": True}, "invalid PostgreSQL logical backup parameters"),
        ({"connect_timeout_seconds": 61}, "invalid PostgreSQL logical backup parameters"),
    ],
)
def test_logical_backup_rejects_untrusted_parameters_before_subprocess(
    tmp_path, monkeypatch, overrides, message
):
    _path, descriptor = _open_private_output(tmp_path)
    called = False

    def forbidden_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(logical_backup.subprocess, "run", forbidden_run)
    parameters = {
        "service_name": "safe_service",
        "output_descriptor": descriptor,
        "pg_dump_executable": "/usr/bin/pg_dump",
        "timeout_seconds": 60,
        "connect_timeout_seconds": 10,
    }
    parameters.update(overrides)
    try:
        with pytest.raises(PostgresLogicalBackupError, match=f"^{message}$"):
            create_postgres_logical_backup(**parameters)
        assert called is False
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_closed_descriptor_before_subprocess(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    os.close(descriptor)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    with pytest.raises(
        PostgresLogicalBackupError,
        match="^PostgreSQL logical backup output could not be inspected$",
    ):
        create_postgres_logical_backup(
            "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
        )


def test_logical_backup_rejects_non_regular_output_before_subprocess(monkeypatch):
    read_descriptor, write_descriptor = os.pipe()
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output must be a private empty regular file$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                write_descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
    finally:
        os.close(read_descriptor)
        os.close(write_descriptor)


def test_logical_backup_rejects_nonempty_output_before_subprocess(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    os.write(descriptor, b"existing")
    os.lseek(descriptor, 0, os.SEEK_SET)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output must be a private empty regular file$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_nonzero_output_offset_before_subprocess(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    os.lseek(descriptor, 1, os.SEEK_SET)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output must start at offset zero$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_group_or_other_readable_output(tmp_path, monkeypatch):
    path, descriptor = _open_private_output(tmp_path)
    os.chmod(path, 0o640)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output must be owner-only$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_hard_linked_output(tmp_path, monkeypatch):
    path, descriptor = _open_private_output(tmp_path)
    os.link(path, tmp_path / "backup-link.dump")
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output must have one link$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("secret path"), "PostgreSQL logical backup executable unavailable"),
        (subprocess.TimeoutExpired("secret command", 1), "PostgreSQL logical backup timed out"),
        (OSError("secret operating-system detail"), "PostgreSQL logical backup execution failed"),
        (RuntimeError("secret lower-layer detail"), "PostgreSQL logical backup execution failed"),
    ],
)
def test_logical_backup_normalizes_execution_failures_and_invalidates_output(
    tmp_path, monkeypatch, failure, message
):
    _path, descriptor = _open_private_output(tmp_path)

    def failing_run(_argv, **kwargs):
        os.write(kwargs["stdout"], b"partial-sensitive-backup")
        raise failure

    monkeypatch.setattr(logical_backup.subprocess, "run", failing_run)
    try:
        with pytest.raises(PostgresLogicalBackupError, match=f"^{message}$") as caught:
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert "secret" not in str(caught.value)
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert _read_descriptor(descriptor) == b""
    finally:
        os.close(descriptor)


def test_logical_backup_preserves_baseexception_and_invalidates_output(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)

    def interrupted_run(_argv, **kwargs):
        os.write(kwargs["stdout"], b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(logical_backup.subprocess, "run", interrupted_run)
    try:
        with pytest.raises(KeyboardInterrupt):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert _read_descriptor(descriptor) == b""
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_nonzero_exit_and_invalidates_output(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)

    def failed_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"partial")
        return subprocess.CompletedProcess(argv, 2)

    monkeypatch.setattr(logical_backup.subprocess, "run", failed_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup command failed$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert _read_descriptor(descriptor) == b""
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_malformed_runner_result(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda _argv, **_kwargs: SimpleNamespace(returncode=0),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup execution failed$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert _read_descriptor(descriptor) == b""
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_empty_success(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output is incomplete$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
    finally:
        os.close(descriptor)


def test_logical_backup_normalizes_success_path_fsync_failure(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    monkeypatch.setattr(logical_backup.subprocess, "run", _write_successfully)
    monkeypatch.setattr(
        logical_backup.os,
        "fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError("secret fsync detail")),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output could not be finalized$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert "secret" not in str(caught.value)
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert _read_descriptor(descriptor) == b""
    finally:
        os.close(descriptor)


def test_logical_backup_normalizes_final_fstat_failure(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    real_fstat = os.fstat
    target_seen = False

    def flaky_fstat(target_descriptor):
        nonlocal target_seen
        status = real_fstat(target_descriptor)
        if target_descriptor != descriptor:
            return status
        if not target_seen:
            target_seen = True
            return status
        raise OSError("secret final stat detail")

    monkeypatch.setattr(logical_backup.subprocess, "run", _write_successfully)
    monkeypatch.setattr(logical_backup.os, "fstat", flaky_fstat)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output could not be finalized$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert _read_descriptor(descriptor) == b""
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "final_override",
    [
        {"st_nlink": 0},
        {"st_mode": stat.S_IFREG | 0o640},
    ],
)
def test_logical_backup_rejects_unsafe_final_output_state(
    tmp_path, monkeypatch, final_override
):
    _path, descriptor = _open_private_output(tmp_path)
    real_fstat = os.fstat
    target_seen = False

    def changed_fstat(target_descriptor):
        nonlocal target_seen
        status = real_fstat(target_descriptor)
        if target_descriptor != descriptor:
            return status
        if not target_seen:
            target_seen = True
            return status
        values = {
            "st_mode": status.st_mode,
            "st_nlink": status.st_nlink,
            "st_size": status.st_size,
        }
        values.update(final_override)
        return SimpleNamespace(**values)

    monkeypatch.setattr(logical_backup.subprocess, "run", _write_successfully)
    monkeypatch.setattr(logical_backup.os, "fstat", changed_fstat)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output became unsafe$",
        ):
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert _read_descriptor(descriptor) == b""
    finally:
        os.close(descriptor)


def test_logical_backup_primary_error_survives_invalidation_failure(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)

    def failed_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"partial")
        return subprocess.CompletedProcess(argv, 3)

    monkeypatch.setattr(logical_backup.subprocess, "run", failed_run)
    monkeypatch.setattr(
        logical_backup.os,
        "ftruncate",
        lambda *_args: (_ for _ in ()).throw(OSError("cleanup secret")),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup command failed$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert "cleanup secret" not in str(caught.value)
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
    finally:
        os.close(descriptor)


def test_logical_backup_primary_error_survives_offset_reset_failure(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)
    real_lseek = os.lseek
    offset_reset_failed = False

    def failed_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"partial")
        return subprocess.CompletedProcess(argv, 4)

    def failing_lseek(target_descriptor, offset, whence):
        nonlocal offset_reset_failed
        if offset == 0 and whence == os.SEEK_SET:
            offset_reset_failed = True
            raise OSError("offset cleanup secret")
        return real_lseek(target_descriptor, offset, whence)

    monkeypatch.setattr(logical_backup.subprocess, "run", failed_run)
    monkeypatch.setattr(logical_backup.os, "lseek", failing_lseek)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup command failed$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service", descriptor, pg_dump_executable="/usr/bin/pg_dump"
            )
        assert "offset cleanup secret" not in str(caught.value)
        assert offset_reset_failed
    finally:
        os.close(descriptor)
