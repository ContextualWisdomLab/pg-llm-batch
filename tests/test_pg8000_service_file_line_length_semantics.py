"""libpq service-file line-length compatibility regressions for pg8000."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import (
    Pg8000CandidateInvalidConninfoError,
)
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def test_service_file_rejects_line_at_libpq_fgets_buffer_limit(tmp_path: Path) -> None:
    """Reject a logical line once libpq's 1024-byte fgets buffer would reject it."""
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

    resolver = Pg8000CandidateServiceFileResolver(service_file)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("analytics")
