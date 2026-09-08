"""Final-component authority regressions for explicit pg8000 service files."""

from __future__ import annotations

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
