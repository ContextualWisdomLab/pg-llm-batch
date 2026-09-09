"""libpq-compatible service-file value regressions for pg8000."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import (
    Pg8000CandidateInvalidConninfoError,
)
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def test_service_file_preserves_leading_value_whitespace_after_equals(tmp_path: Path) -> None:
    """Preserve leading value bytes after ``=`` as PostgreSQL service files do."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[analytics]\n"
        "host=db.example\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n"
        "password= service-secret\n",
        encoding="utf-8",
    )

    resolver = Pg8000CandidateServiceFileResolver(service_file)

    assert resolver("analytics")["password"] == " service-secret"


def test_service_file_rejects_whitespace_before_equals_like_libpq(tmp_path: Path) -> None:
    """Reject a key whose bytes include whitespace before the ``=`` delimiter."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[analytics]\n"
        "host =db.example\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n",
        encoding="utf-8",
    )

    resolver = Pg8000CandidateServiceFileResolver(service_file)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("analytics")
