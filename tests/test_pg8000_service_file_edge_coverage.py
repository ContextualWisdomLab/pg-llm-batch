"""Edge contracts for the explicit pg8000 candidate service-file capability."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import Pg8000CandidateInvalidConninfoError
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def test_service_resolver_requires_path_capability() -> None:
    """A shaped string cannot become implicit filesystem authority."""
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver("service.conf")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "content",
    [
        "[prod]\nhost=local\x7fhost\nuser=u\ndbname=d\n",
        "[prod\nhost=localhost\nuser=u\ndbname=d\n",
        "[prod]]\nhost=localhost\nuser=u\ndbname=d\n",
        "[other]\nhost=localhost\nuser=u\ndbname=d\n",
    ],
)
def test_service_resolver_rejects_malformed_or_missing_target(
    tmp_path: Path,
    content: str,
) -> None:
    """Malformed framing and absent selected stanzas fail without fallback discovery."""
    path = tmp_path / "pg_service.conf"
    path.write_text(content, encoding="utf-8")
    resolver = Pg8000CandidateServiceFileResolver(path)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("prod")


def test_service_resolver_skips_comments_blank_lines_and_non_target_values(tmp_path: Path) -> None:
    """Only the selected stanza contributes connection authority."""
    path = tmp_path / "pg_service.conf"
    path.write_text(
        "# comment\n\n[other]\nunsupported=value\n[prod]\nhost=localhost\nuser=u\ndbname=d\n",
        encoding="utf-8",
    )
    assert Pg8000CandidateServiceFileResolver(path)("prod") == {
        "host": "localhost",
        "user": "u",
        "dbname": "d",
    }
