# SPDX-License-Identifier: Apache-2.0
"""Regression contract for binding a PostgreSQL data-directory FD to cluster identity."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pg_llm_batch.postgres_data_directory_identity import (
    PostgresDataDirectoryIdentityError,
    verify_postgres_data_directory_identity,
)
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


_SYSTEM_IDENTIFIER = 7_394_886_517_812_345_678
_OVERSIZED_DESCRIPTOR = 1 << 128


def _open_directory(path: Path) -> int:
    """Open a caller-owned directory descriptor for one test."""
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _open_control_script(tmp_path: Path, body: str, *, mode: int = 0o700) -> int:
    """Open an executable FD that behaves like bounded pg_controldata."""
    script = tmp_path / "pg_controldata-fixture"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(mode)
    return os.open(script, os.O_RDONLY)


def _expected_identity(value: int = _SYSTEM_IDENTIFIER) -> PostgresRestoreTargetIdentity:
    """Return one exact protected-main restore-target identity."""
    return PostgresRestoreTargetIdentity(system_identifier=value)


def test_verifier_binds_directory_fd_to_exact_cluster_identity(tmp_path: Path) -> None:
    control_fd = _open_control_script(
        tmp_path,
        f"printf 'Database system identifier:           {_SYSTEM_IDENTIFIER}\\n'\n",
    )
    directory = tmp_path / "restore-data"
    directory.mkdir()
    directory_fd = _open_directory(directory)
    try:
        verify_postgres_data_directory_identity(
            data_directory_fd=directory_fd,
            pg_controldata_fd=control_fd,
            expected_identity=_expected_identity(),
        )
    finally:
        os.close(directory_fd)
        os.close(control_fd)


def test_verifier_rejects_directory_identity_mismatch(tmp_path: Path) -> None:
    control_fd = _open_control_script(
        tmp_path,
        f"printf 'Database system identifier:           {_SYSTEM_IDENTIFIER}\\n'\n",
    )
    directory = tmp_path / "restore-data"
    directory.mkdir()
    directory_fd = _open_directory(directory)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^PostgreSQL data directory does not match restore target identity$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(_SYSTEM_IDENTIFIER - 1),
            )
    finally:
        os.close(directory_fd)
        os.close(control_fd)


def test_verifier_snapshots_expected_identity_before_child_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caller mutation cannot rewrite the authority already accepted for this call."""
    expected_identity = _expected_identity(_SYSTEM_IDENTIFIER - 1)
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    directory = tmp_path / "restore-data"
    directory.mkdir()
    directory_fd = _open_directory(directory)

    def mutate_identity_during_inspection(
        args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        object.__setattr__(
            expected_identity,
            "system_identifier",
            _SYSTEM_IDENTIFIER,
        )
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"Database system identifier: {_SYSTEM_IDENTIFIER}\n".encode("ascii"),
        )

    monkeypatch.setattr(subprocess, "run", mutate_identity_during_inspection)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^PostgreSQL data directory does not match restore target identity$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=expected_identity,
            )
    finally:
        os.close(directory_fd)
        os.close(control_fd)


def test_verifier_rejects_mutated_invalid_expected_identity(tmp_path: Path) -> None:
    """An exact identity object mutated after construction still fails closed."""
    expected_identity = _expected_identity()
    object.__setattr__(expected_identity, "system_identifier", 0)
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    directory = tmp_path / "restore-data"
    directory.mkdir()
    directory_fd = _open_directory(directory)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=expected_identity,
            )
    finally:
        os.close(directory_fd)
        os.close(control_fd)


@pytest.mark.parametrize(
    "output",
    [
        b"",
        b"Catalog version number: 202607171\n",
        b"Database system identifier: 0\n",
        b"Database system identifier: -1\n",
        b"Database system identifier: +1\n",
        b"Database system identifier: 18446744073709551616\n",
        b"Database system identifier: not-a-number\n",
        b"Database system identifier: 1\nDatabase system identifier: 2\n",
        b"Database system identifier: \xff\n",
    ],
)
def test_verifier_rejects_untrusted_control_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    directory = tmp_path / "restore-data"
    directory.mkdir()
    directory_fd = _open_directory(directory)
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
                data_directory_fd=directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(directory_fd)
        os.close(control_fd)


def test_verifier_rejects_oversized_control_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    directory = tmp_path / "restore-data"
    directory.mkdir()
    directory_fd = _open_directory(directory)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"x" * 16_385
        ),
    )
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^could not inspect PostgreSQL data-directory identity$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(directory_fd)
        os.close(control_fd)


@pytest.mark.parametrize(
    "value", [-1, True, False, 1.0, "1", None, _OVERSIZED_DESCRIPTOR]
)
def test_verifier_rejects_invalid_directory_descriptor(
    tmp_path: Path, value: Any
) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=value,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(control_fd)


@pytest.mark.parametrize(
    "value", [-1, True, False, 1.0, "1", None, _OVERSIZED_DESCRIPTOR]
)
def test_verifier_rejects_invalid_control_descriptor(
    tmp_path: Path, value: Any
) -> None:
    directory = tmp_path / "restore-data"
    directory.mkdir()
    directory_fd = _open_directory(directory)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=directory_fd,
                pg_controldata_fd=value,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(directory_fd)


def test_verifier_rejects_non_directory_data_fd(tmp_path: Path) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    plain_file = tmp_path / "not-a-directory"
    plain_file.write_bytes(b"")
    plain_fd = os.open(plain_file, os.O_RDONLY)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=plain_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(plain_fd)
        os.close(control_fd)


def test_verifier_rejects_non_regular_control_fd(tmp_path: Path) -> None:
    control_directory = tmp_path / "control-directory"
    control_directory.mkdir()
    control_fd = _open_directory(control_directory)
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)


def test_verifier_rejects_non_executable_control_fd(tmp_path: Path) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n", mode=0o600)
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)


def test_verifier_rejects_closed_descriptors(tmp_path: Path) -> None:
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    os.close(data_directory_fd)
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(control_fd)


def test_verifier_rejects_fabricated_expected_identity(tmp_path: Path) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=object(),  # type: ignore[arg-type]
            )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)


@pytest.mark.parametrize(
    "effect",
    [
        subprocess.CompletedProcess(["pg_controldata"], 1, stdout=b"diagnostic"),
        subprocess.TimeoutExpired(["pg_controldata"], 5.0),
        OSError("sensitive executable diagnostic"),
    ],
)
def test_verifier_fails_closed_on_control_process_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    effect: object,
) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if isinstance(effect, BaseException):
            raise effect
        assert isinstance(effect, subprocess.CompletedProcess)
        return effect

    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^could not inspect PostgreSQL data-directory identity$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)


def test_verifier_uses_only_fd_capabilities_and_bounded_child_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    observed: dict[str, object] = {}

    def fake_run(args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["args"] = args
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"Database system identifier: {_SYSTEM_IDENTIFIER}\n".encode("ascii"),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        verify_postgres_data_directory_identity(
            data_directory_fd=data_directory_fd,
            pg_controldata_fd=control_fd,
            expected_identity=_expected_identity(),
        )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)

    pass_fds = observed["pass_fds"]
    assert isinstance(pass_fds, tuple)
    assert len(pass_fds) == 2
    control_snapshot_fd, data_snapshot_fd = pass_fds
    assert type(control_snapshot_fd) is int
    assert type(data_snapshot_fd) is int
    assert control_snapshot_fd != control_fd
    assert data_snapshot_fd != data_directory_fd
    assert observed["args"] == (
        f"/proc/self/fd/{control_snapshot_fd}",
        "-D",
        f"/proc/self/fd/{data_snapshot_fd}",
    )
    assert observed["stdin"] is subprocess.DEVNULL
    assert observed["stdout"] is subprocess.PIPE
    assert observed["stderr"] is subprocess.DEVNULL
    assert observed["check"] is False
    assert observed["timeout"] == 5.0
    assert observed["cwd"] == "/"
    assert observed["env"] == {"LANG": "C", "LC_ALL": "C", "PG_COLOR": "never"}
    assert observed["close_fds"] is True
    with pytest.raises(OSError):
        os.fstat(control_snapshot_fd)
    with pytest.raises(OSError):
        os.fstat(data_snapshot_fd)


def test_verifier_rejects_closed_control_descriptor(tmp_path: Path) -> None:
    """Fail closed when the trusted executable capability is no longer open."""
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    os.close(control_fd)
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^invalid PostgreSQL data-directory identity inputs$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(data_directory_fd)


@pytest.mark.parametrize("stdout", [None, "Database system identifier: 1\n"])
def test_verifier_rejects_non_bytes_control_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: object,
) -> None:
    """Reject malformed child-process objects without leaking their content."""
    control_fd = _open_control_script(tmp_path, "exit 0\n")
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir()
    data_directory_fd = _open_directory(data_directory)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=stdout),
    )
    try:
        with pytest.raises(
            PostgresDataDirectoryIdentityError,
            match="^could not inspect PostgreSQL data-directory identity$",
        ):
            verify_postgres_data_directory_identity(
                data_directory_fd=data_directory_fd,
                pg_controldata_fd=control_fd,
                expected_identity=_expected_identity(),
            )
    finally:
        os.close(data_directory_fd)
        os.close(control_fd)
