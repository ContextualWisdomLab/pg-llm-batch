"""Parent-directory authority regressions for explicit pg8000 service files."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import Pg8000CandidateInvalidConninfoError
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def _write_service_file(path: Path, *, host: str) -> None:
    """Write one bounded service stanza for the parent-authority specimen."""
    path.write_text(
        "[analytics]\n"
        f"host={host}\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n",
        encoding="utf-8",
    )


def test_candidate_service_file_rejects_parent_directory_replacement(
    tmp_path: Path,
) -> None:
    """Do not let a replaced parent directory redirect retained file authority."""
    selected_parent = tmp_path / "selected"
    selected_parent.mkdir()
    selected_file = selected_parent / "pg_service.conf"
    _write_service_file(selected_file, host="selected.example")

    resolver = Pg8000CandidateServiceFileResolver(selected_file)

    retained_parent = tmp_path / "selected-retained"
    selected_parent.rename(retained_parent)
    selected_parent.mkdir()
    _write_service_file(selected_parent / "pg_service.conf", host="redirected.example")

    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is invalid",
    ):
        resolver("analytics")
