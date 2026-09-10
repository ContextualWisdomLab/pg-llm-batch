"""Final-component authority regressions for explicit pg8000 service files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import Pg8000CandidateInvalidConninfoError
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def test_candidate_service_file_rejects_final_symlink_authority(tmp_path: Path) -> None:
    """Reject a final symlink before it can redirect connection-selector authority."""
    target = tmp_path / "actual.conf"
    target.write_text(
        "[analytics]\n"
        "host=redirected.example\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n",
        encoding="utf-8",
    )
    service_file = tmp_path / "pg_service.conf"
    try:
        service_file.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("filesystem does not support symlinks")

    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is invalid",
    ):
        Pg8000CandidateServiceFileResolver(service_file)("analytics")


def test_candidate_service_file_rejects_path_substitution_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the selected inode when pathname resolution changes before open."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[analytics]\nhost=selected.example\nport=5432\ndbname=batch\nuser=batch\n",
        encoding="utf-8",
    )
    replacement = tmp_path / "replacement.conf"
    replacement.write_text(
        "[analytics]\nhost=redirected.example\nport=5432\ndbname=batch\nuser=batch\n",
        encoding="utf-8",
    )
    real_open = os.open

    def substituted_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and Path(path) == Path(service_file.name):
            return real_open(replacement.name, flags, mode, dir_fd=dir_fd)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", substituted_open)

    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is invalid",
    ):
        Pg8000CandidateServiceFileResolver(service_file)("analytics")


def test_candidate_service_file_normalizes_open_failure_after_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed if the selected regular path cannot be opened after preflight."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[analytics]\nhost=selected.example\nport=5432\ndbname=batch\nuser=batch\n",
        encoding="utf-8",
    )
    real_open = os.open

    def failing_file_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None:
            raise OSError("synthetic path-open failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", failing_file_open)

    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is invalid",
    ):
        Pg8000CandidateServiceFileResolver(service_file)("analytics")
