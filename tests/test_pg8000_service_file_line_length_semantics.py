"""libpq service-file line-length compatibility regressions for pg8000."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import (
    Pg8000CandidateInvalidConninfoError,
)
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def test_service_file_rejects_line_at_libpq_fgets_buffer_limit(tmp_path: Path) -> None:
    """Reject a newline-terminated line once libpq's 1024-byte buffer would reject it."""
    service_file = tmp_path / "pg_service.conf"
    host_line = "host=" + ("a" * 1017)
    assert len((host_line + "\n").encode("utf-8")) == 1023
    service_file.write_text(
        "[analytics]\n"
        f"{host_line}\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n",
        encoding="utf-8",
    )

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(service_file)


def test_service_file_rejects_unterminated_line_at_libpq_fgets_buffer_limit(
    tmp_path: Path,
) -> None:
    """Apply the same byte bound to a final service-file line without LF."""
    service_file = tmp_path / "pg_service.conf"
    host_line = "host=" + ("a" * 1018)
    assert len(host_line.encode("utf-8")) == 1023
    service_file.write_text(
        "[analytics]\n"
        "port=5432\n"
        "dbname=batch\n"
        "user=batch\n"
        f"{host_line}",
        encoding="utf-8",
    )

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(service_file)
