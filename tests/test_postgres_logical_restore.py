# SPDX-License-Identifier: Apache-2.0
"""Regression tests for bounded PostgreSQL logical restore execution."""

from __future__ import annotations

import os
import stat
import subprocess
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_logical_restore as logical_restore
from pg_llm_batch.postgres_logical_restore import (
    PostgresLogicalRestoreError,
    PostgresLogicalRestoreResult,
    restore_postgres_logical_backup,
)


def _open_private_archive(tmp_path, payload=b"PGDMP-archive"):
    path = tmp_path / "backup.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.write(descriptor, payload)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return path, descriptor, len(payload)


def _consume_successfully(argv, **kwargs):
    while os.read(kwargs["stdin"], 1024):
        pass
    return subprocess.CompletedProcess(argv, 0)


def _restore_trusted(service_name, descriptor, **kwargs):
    return restore_postgres_logical_backup(
        service_name,
        descriptor,
        source_superusers_trusted=True,
        **kwargs,
    )


def test_restore_refuses_implicit_source_trust_before_subprocess(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    called = False

    def forbidden_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("untrusted archive must not execute")

    monkeypatch.setattr(logical_restore.subprocess, "run", forbidden_run)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore requires trusted source superusers$",
        ):
            restore_postgres_logical_backup(
                "isolated_restore",
                descriptor,
                pg_restore_executable="/usr/bin/pg_restore",
            )
        assert called is False
    finally:
        os.close(descriptor)


def test_restore_uses_shell_free_bounded_content_free_contract(tmp_path, monkeypatch):
    path, descriptor, size = _open_private_archive(tmp_path)
    observed = {}
    monkeypatch.setenv("PGSERVICEFILE", "/run/secrets/pg_service.conf")
    monkeypatch.setenv("PGPASSWORD", "credential-value")
    monkeypatch.setenv("PGPASSFILE", "/run/secrets/pgpass")
    monkeypatch.setenv("PGHOST", "attacker-controlled-host")
    monkeypatch.setenv("PGDATABASE", "attacker-controlled-database")
    monkeypatch.setenv("PGOPTIONS", "-c search_path=attacker")
    monkeypatch.setenv("PGSSLMODE", "disable")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "must-not-reach-pg-restore")

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return _consume_successfully(argv, **kwargs)

    monkeypatch.setattr(logical_restore.subprocess, "run", fake_run)
    try:
        result = _restore_trusted(
            "isolated_restore",
            descriptor,
            pg_restore_executable="/usr/lib/postgresql/18/bin/pg_restore",
            timeout_seconds=41,
            connect_timeout_seconds=9,
            maximum_archive_size_bytes=1024,
        )
        assert result == PostgresLogicalRestoreResult(size_bytes=size)
        assert observed["argv"] == [
            "/usr/lib/postgresql/18/bin/pg_restore",
            "--single-transaction",
            "--exit-on-error",
            "--dbname=service=isolated_restore",
        ]
        assert observed["kwargs"]["stdin"] == descriptor
        assert observed["kwargs"]["stdout"] is subprocess.DEVNULL
        assert observed["kwargs"]["stderr"] is subprocess.DEVNULL
        assert observed["kwargs"]["timeout"] == 41
        assert observed["kwargs"]["check"] is False
        assert observed["kwargs"]["close_fds"] is True
        assert observed["kwargs"]["env"] == {
            "PGSERVICEFILE": "/run/secrets/pg_service.conf",
            "PGPASSWORD": "credential-value",
            "PGPASSFILE": "/run/secrets/pgpass",
            "PGCONNECT_TIMEOUT": "9",
        }
        assert str(path) not in " ".join(observed["argv"])
        assert "credential-value" not in " ".join(observed["argv"])
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == size
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "overrides",
    [
        {"service_name": ""},
        {"service_name": "bad service"},
        {"service_name": type("Text", (str,), {})("safe")},
        {"input_descriptor": True},
        {"input_descriptor": -1},
        {"pg_restore_executable": "pg_restore"},
        {"pg_restore_executable": "/usr/bin/not-pg-restore"},
        {"pg_restore_executable": type("Text", (str,), {})("/usr/bin/pg_restore")},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
        {"timeout_seconds": 86401},
        {"connect_timeout_seconds": 0},
        {"connect_timeout_seconds": True},
        {"connect_timeout_seconds": 61},
        {"maximum_archive_size_bytes": 0},
        {"maximum_archive_size_bytes": True},
        {"maximum_archive_size_bytes": (1 << 63)},
        {"source_superusers_trusted": 1},
    ],
)
def test_restore_rejects_untrusted_parameters_before_subprocess(
    tmp_path, monkeypatch, overrides
):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    called = False

    def forbidden_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(logical_restore.subprocess, "run", forbidden_run)
    parameters = {
        "service_name": "safe_service",
        "input_descriptor": descriptor,
        "pg_restore_executable": "/usr/bin/pg_restore",
        "timeout_seconds": 60,
        "connect_timeout_seconds": 10,
        "maximum_archive_size_bytes": 4096,
        "source_superusers_trusted": True,
    }
    parameters.update(overrides)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^invalid PostgreSQL logical restore parameters$",
        ):
            restore_postgres_logical_backup(**parameters)
        assert called is False
    finally:
        os.close(descriptor)


def test_restore_rejects_closed_descriptor_before_subprocess(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    os.close(descriptor)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    with pytest.raises(
        PostgresLogicalRestoreError,
        match="^PostgreSQL logical restore archive could not be inspected$",
    ):
        _restore_trusted(
            "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
        )


def test_restore_rejects_non_regular_input_before_subprocess(monkeypatch):
    read_descriptor, write_descriptor = os.pipe()
    os.write(write_descriptor, b"archive")
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must be a private regular file$",
        ):
            _restore_trusted(
                "safe_service",
                read_descriptor,
                pg_restore_executable="/usr/bin/pg_restore",
            )
    finally:
        os.close(read_descriptor)
        os.close(write_descriptor)


def test_restore_rejects_empty_input_before_subprocess(tmp_path, monkeypatch):
    path = tmp_path / "empty.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must be non-empty and bounded$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


def test_restore_rejects_oversized_input_before_subprocess(tmp_path, monkeypatch):
    _path, descriptor, size = _open_private_archive(tmp_path)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must be non-empty and bounded$",
        ):
            _restore_trusted(
                "safe_service",
                descriptor,
                pg_restore_executable="/usr/bin/pg_restore",
                maximum_archive_size_bytes=size - 1,
            )
    finally:
        os.close(descriptor)


def test_restore_rejects_nonzero_input_offset_before_subprocess(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    os.lseek(descriptor, 1, os.SEEK_SET)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must start at offset zero$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


def test_restore_rejects_group_or_other_readable_input(tmp_path, monkeypatch):
    path, descriptor, _size = _open_private_archive(tmp_path)
    os.chmod(path, 0o640)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must be owner-only$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


def test_restore_rejects_hard_linked_input(tmp_path, monkeypatch):
    path, descriptor, _size = _open_private_archive(tmp_path)
    os.link(path, tmp_path / "backup-link.dump")
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive must have one link$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("secret path"), "PostgreSQL logical restore executable unavailable"),
        (subprocess.TimeoutExpired("secret command", 1), "PostgreSQL logical restore timed out"),
        (OSError("secret operating-system detail"), "PostgreSQL logical restore execution failed"),
        (RuntimeError("secret lower-layer detail"), "PostgreSQL logical restore execution failed"),
    ],
)
def test_restore_normalizes_execution_failures(tmp_path, monkeypatch, failure, message):
    _path, descriptor, _size = _open_private_archive(tmp_path)

    def failing_run(_argv, **_kwargs):
        raise failure

    monkeypatch.setattr(logical_restore.subprocess, "run", failing_run)
    try:
        with pytest.raises(PostgresLogicalRestoreError, match=f"^{message}$") as caught:
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
        assert "secret" not in str(caught.value)
    finally:
        os.close(descriptor)


def test_restore_preserves_baseexception(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


def test_restore_rejects_nonzero_exit(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 2),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore command failed$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


def test_restore_rejects_malformed_runner_result(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda _argv, **_kwargs: SimpleNamespace(returncode=0),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore execution failed$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


def test_restore_requires_complete_archive_consumption(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
    monkeypatch.setattr(
        logical_restore.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0),
    )
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive was not consumed completely$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)


def test_restore_normalizes_final_inspection_failure(tmp_path, monkeypatch):
    _path, descriptor, _size = _open_private_archive(tmp_path)
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

    monkeypatch.setattr(logical_restore.subprocess, "run", _consume_successfully)
    monkeypatch.setattr(logical_restore.os, "fstat", flaky_fstat)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive could not be verified$",
        ) as caught:
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
        assert "secret" not in str(caught.value)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "final_override",
    [
        {"st_size": 1},
        {"st_nlink": 0},
        {"st_mode": stat.S_IFREG | 0o640},
    ],
)
def test_restore_rejects_archive_mutation_during_execution(
    tmp_path, monkeypatch, final_override
):
    _path, descriptor, _size = _open_private_archive(tmp_path)
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

    monkeypatch.setattr(logical_restore.subprocess, "run", _consume_successfully)
    monkeypatch.setattr(logical_restore.os, "fstat", changed_fstat)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive changed during execution$",
        ):
            _restore_trusted(
                "safe_service", descriptor, pg_restore_executable="/usr/bin/pg_restore"
            )
    finally:
        os.close(descriptor)
