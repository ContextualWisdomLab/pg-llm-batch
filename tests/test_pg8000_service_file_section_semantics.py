"""libpq-compatible service-file section identity regressions for pg8000."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import (
    Pg8000CandidateInvalidConninfoError,
)
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def test_service_file_does_not_normalize_whitespace_inside_section_identity(
    tmp_path: Path,
) -> None:
    """Do not turn a differently named libpq section into the requested service."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[ analytics ]\n"
        "host=db.example\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n",
        encoding="utf-8",
    )

    resolver = Pg8000CandidateServiceFileResolver(service_file)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("analytics")


def test_service_file_does_not_treat_unicode_space_as_libpq_line_framing(
    tmp_path: Path,
) -> None:
    """Do not promote a section hidden behind UTF-8 non-ASCII whitespace."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "\u00a0[analytics]\n"
        "host=db.example\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n",
        encoding="utf-8",
    )

    resolver = Pg8000CandidateServiceFileResolver(service_file)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("analytics")
