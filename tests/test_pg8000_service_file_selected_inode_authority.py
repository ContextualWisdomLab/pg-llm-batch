"""Selected-file identity regressions for explicit pg8000 service files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import Pg8000CandidateInvalidConninfoError
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def _write_service_file(path: Path, *, host: str) -> None:
    """Write one bounded service stanza for selected-file authority evidence."""
    path.write_text(
        "[analytics]\n"
        f"host={host}\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n",
        encoding="utf-8",
    )


def test_candidate_service_file_rejects_selected_inode_replacement(
    tmp_path: Path,
) -> None:
    """Do not let a later regular-file replacement redirect retained authority."""
    service_file = tmp_path / "pg_service.conf"
    _write_service_file(service_file, host="selected.example")
    resolver = Pg8000CandidateServiceFileResolver(service_file)

    replacement = tmp_path / "replacement.conf"
    _write_service_file(replacement, host="redirected.example")
    os.replace(replacement, service_file)

    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is invalid",
    ):
        resolver("analytics")


def test_candidate_service_file_rejects_same_inode_content_replacement(
    tmp_path: Path,
) -> None:
    """Do not let in-place edits change connection authority after construction."""
    service_file = tmp_path / "pg_service.conf"
    _write_service_file(service_file, host="selected.example")
    selected_identity = (service_file.stat().st_dev, service_file.stat().st_ino)
    resolver = Pg8000CandidateServiceFileResolver(service_file)

    _write_service_file(service_file, host="redirected.example")
    assert (service_file.stat().st_dev, service_file.stat().st_ino) == selected_identity

    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is invalid",
    ):
        resolver("analytics")
