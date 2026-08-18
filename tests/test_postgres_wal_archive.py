# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL WAL archive reception."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_wal_archive import (
    PostgresWalArchiveError,
    PostgresWalArchiveResult,
    receive_postgres_wal_archive,
)


def _open_private_directory(tmp_path: Path, name: str = "wal-archive") -> tuple[Path, int]:
    path = tmp_path / name
    path.mkdir(mode=0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    return path, descriptor


def test_success_uses_slot_end_lsn_synchronous_flush_and_restricted_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded receiver snapshots one private archive directory into a private fd."""
    _path, descriptor = _open_private_directory(tmp_path)
    monkeypatch.setenv("PGPASSWORD", "secret-password")
    monkeypatch.setenv("PGPASSFILE", "/run/secrets/pgpass")
    monkeypatch.delenv("PGSERVICEFILE", raising=False)
    monkeypatch.setenv("PGHOST", "must-not-inherit")
    monkeypatch.setenv("PGAPPNAME", "must-be-overridden")
    captured: dict[str, object] = {}

    def successful_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        captured["arguments"] = arguments
        captured.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", successful_run)
    try:
        result = receive_postgres_wal_archive(
            "physical_replication_source",
            "pg_llm_batch_archive",
            "16/B374D848",
            descriptor,
            pg_receivewal_executable="/usr/lib/postgresql/18/bin/pg_receivewal",
            timeout_seconds=3600,
            connect_timeout_seconds=17,
        )
        assert result == PostgresWalArchiveResult(end_lsn="16/B374D848")
        pass_fds = captured["pass_fds"]
        assert isinstance(pass_fds, tuple) and len(pass_fds) == 1
        private_descriptor = pass_fds[0]
        assert isinstance(private_descriptor, int)
        assert private_descriptor != descriptor
        assert captured["arguments"] == [
            "/usr/lib/postgresql/18/bin/pg_receivewal",
            f"--directory=/proc/self/fd/{private_descriptor}",
            "--endpos=16/B374D848",
            "--slot=pg_llm_batch_archive",
            "--synchronous",
            "--no-loop",
            "--no-password",
        ]
        assert captured["stdin"] is subprocess.DEVNULL
        assert captured["stdout"] is subprocess.DEVNULL
        assert captured["stderr"] is subprocess.DEVNULL
        assert captured["timeout"] == 3600
        assert captured["check"] is False
        assert captured["close_fds"] is True
        assert captured["env"] == {
            "PGPASSWORD": "secret-password",
            "PGPASSFILE": "/run/secrets/pgpass",
            "PGSERVICE": "physical_replication_source",
            "PGCONNECT_TIMEOUT": "17",
            "PGAPPNAME": "pg_llm_batch_wal_archive",
        }
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_name", ""),
        ("service_name", "contains space"),
        ("service_name", "x" * 65),
        ("service_name", 1),
        ("slot_name", ""),
        ("slot_name", "UpperCase"),
        ("slot_name", "dash-not-allowed"),
        ("slot_name", "x" * 64),
        ("slot_name", 1),
        ("end_lsn", ""),
        ("end_lsn", "16/nothex"),
        ("end_lsn", "100000000/1"),
        ("end_lsn", 1),
        ("archive_directory_descriptor", True),
        ("archive_directory_descriptor", -1),
        ("pg_receivewal_executable", "pg_receivewal"),
        ("pg_receivewal_executable", "/usr/bin/not-receivewal"),
        ("pg_receivewal_executable", 1),
        ("timeout_seconds", True),
        ("timeout_seconds", 0),
        ("timeout_seconds", 86_401),
        ("connect_timeout_seconds", True),
        ("connect_timeout_seconds", 0),
        ("connect_timeout_seconds", 61),
    ],
)
def test_invalid_authority_is_rejected_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    """Exact types, names, LSN syntax, executable identity, and budgets fail closed."""
    _path, descriptor = _open_private_directory(tmp_path)
    arguments: dict[str, object] = {
        "service_name": "physical_replication_source",
        "slot_name": "pg_llm_batch_archive",
        "end_lsn": "16/B374D848",
        "archive_directory_descriptor": descriptor,
        "pg_receivewal_executable": "/usr/bin/pg_receivewal",
        "timeout_seconds": 1800,
        "connect_timeout_seconds": 15,
    }
    arguments[field] = value

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("invalid parameters must not execute pg_receivewal")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="^invalid PostgreSQL WAL archive parameters$",
        ):
            receive_postgres_wal_archive(**arguments)  # type: ignore[arg-type]
    finally:
        os.close(descriptor)


def test_archive_directory_retention_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Descriptor snapshot failures disclose no OS diagnostics and execute no receiver."""
    _path, descriptor = _open_private_directory(tmp_path)

    def broken_dup(_descriptor: int) -> int:
        raise OSError("sensitive descriptor diagnostic")

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("unretained directory authority must not execute pg_receivewal")

    monkeypatch.setattr(os, "dup", broken_dup)
    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(PostgresWalArchiveError, match="could not be retained") as caught:
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
        assert "sensitive" not in str(caught.value)
    finally:
        os.close(descriptor)


def test_private_descriptor_close_failure_does_not_replace_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort private-fd cleanup cannot replace completed receive evidence."""
    _path, descriptor = _open_private_directory(tmp_path)
    real_close = os.close

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )

    def fail_private_close(fd: int) -> None:
        if fd != descriptor:
            raise OSError("sensitive private close diagnostic")
        real_close(fd)

    monkeypatch.setattr(os, "close", fail_private_close)
    try:
        assert receive_postgres_wal_archive(
            "physical_replication_source",
            "pg_llm_batch_archive",
            "16/B374D848",
            descriptor,
            pg_receivewal_executable="/usr/bin/pg_receivewal",
        ) == PostgresWalArchiveResult(end_lsn="16/B374D848")
    finally:
        real_close(descriptor)


def test_archive_directory_must_be_private_process_owned_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sensitive WAL cannot be written to regular, permissive, or foreign-owned storage."""
    regular_path = tmp_path / "not-a-directory"
    regular_path.write_bytes(b"")
    regular_descriptor = os.open(regular_path, os.O_RDONLY)
    try:
        with pytest.raises(PostgresWalArchiveError, match="private directory"):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                regular_descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(regular_descriptor)

    path, descriptor = _open_private_directory(tmp_path, "permissive")
    os.chmod(path, 0o750)
    try:
        with pytest.raises(PostgresWalArchiveError, match="owner-only"):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(descriptor)

    _path, descriptor = _open_private_directory(tmp_path, "foreign-owner")
    actual_owner = os.fstat(descriptor).st_uid
    monkeypatch.setattr(os, "geteuid", lambda: actual_owner + 1)
    try:
        with pytest.raises(PostgresWalArchiveError, match="effective process user"):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(descriptor)


def test_archive_directory_must_start_empty_before_bounded_receive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-existing entries cannot choose pg_receivewal's local starting position."""
    path, descriptor = _open_private_directory(tmp_path, "prepopulated")
    (path / "000000010000000000000001").write_bytes(b"stale-wal-like-entry")

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("pre-existing archive state must fail before pg_receivewal")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(PostgresWalArchiveError, match="must start empty"):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(descriptor)


def test_directory_inspection_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OS inspection diagnostics are not exposed through the package error boundary."""
    _path, descriptor = _open_private_directory(tmp_path)

    def broken_fstat(_descriptor: int) -> os.stat_result:
        raise OSError("sensitive directory diagnostic")

    monkeypatch.setattr(os, "fstat", broken_fstat)
    try:
        with pytest.raises(PostgresWalArchiveError, match="could not be inspected") as caught:
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
        assert "sensitive" not in str(caught.value)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("secret executable path"), "executable unavailable"),
        (subprocess.TimeoutExpired(["secret"], 1), "timed out"),
        (RuntimeError("secret provider diagnostic"), "execution failed"),
    ],
)
def test_execution_failures_are_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    message: str,
) -> None:
    """Known command failures disclose no connection or process diagnostics."""
    _path, descriptor = _open_private_directory(tmp_path)

    def exploding_run(*_args: object, **_kwargs: object) -> NoReturn:
        raise failure

    monkeypatch.setattr(subprocess, "run", exploding_run)
    try:
        with pytest.raises(PostgresWalArchiveError, match=message) as caught:
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
        assert "secret" not in str(caught.value)
    finally:
        os.close(descriptor)


def test_baseexception_propagates_without_reclassification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation-like BaseException signals retain their original type."""
    _path, descriptor = _open_private_directory(tmp_path)

    class Cancelled(BaseException):
        pass

    def cancelling_run(*_args: object, **_kwargs: object) -> NoReturn:
        raise Cancelled()

    monkeypatch.setattr(subprocess, "run", cancelling_run)
    try:
        with pytest.raises(Cancelled):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(descriptor)


def test_nonstandard_or_failed_completed_process_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only an exact zero-return CompletedProcess can authorize archive completion."""
    for name, result in [
        ("wrong-type", object()),
        ("nonzero", subprocess.CompletedProcess(["pg_receivewal"], 3)),
    ]:
        _path, descriptor = _open_private_directory(tmp_path, name)

        def returning_run(*_args: object, **_kwargs: object) -> object:
            return result

        monkeypatch.setattr(subprocess, "run", returning_run)
        try:
            with pytest.raises(PostgresWalArchiveError, match="command failed|execution failed"):
                receive_postgres_wal_archive(
                    "physical_replication_source",
                    "pg_llm_batch_archive",
                    "16/B374D848",
                    descriptor,
                    pg_receivewal_executable="/usr/bin/pg_receivewal",
                )
        finally:
            os.close(descriptor)


def test_finalization_rejects_permission_owner_or_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful process cannot authorize a directory whose security identity changed."""
    path, descriptor = _open_private_directory(tmp_path, "mode-drift")

    def permission_drift(
        arguments: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        os.chmod(path, 0o755)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", permission_drift)
    try:
        with pytest.raises(PostgresWalArchiveError, match="became unsafe"):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.chmod(path, 0o700)
        os.close(descriptor)

    _path, descriptor = _open_private_directory(tmp_path, "identity-drift")
    real_fstat = os.fstat
    private_calls = 0

    def changed_identity(fd: int) -> os.stat_result:
        nonlocal private_calls
        status = real_fstat(fd)
        if fd == descriptor:
            return status
        private_calls += 1
        if private_calls == 1:
            return status
        fields = list(status)
        fields[1] = status.st_ino + 1
        return os.stat_result(fields)

    monkeypatch.setattr(os, "fstat", changed_identity)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )
    try:
        with pytest.raises(PostgresWalArchiveError, match="changed during execution"):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(descriptor)


def test_final_sync_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Directory durability failure blocks success without leaking OS diagnostics."""
    _path, descriptor = _open_private_directory(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )

    def broken_fsync(_descriptor: int) -> None:
        raise OSError("sensitive sync diagnostic")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    try:
        with pytest.raises(PostgresWalArchiveError, match="could not be finalized") as caught:
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
        assert "sensitive" not in str(caught.value)
    finally:
        os.close(descriptor)
