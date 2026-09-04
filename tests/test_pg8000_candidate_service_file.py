"""Candidate service-file resolver regressions for the PostgreSQL migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch.pg8000_candidate_driver_port import Pg8000CandidateInvalidConninfoError
from pg_llm_batch.pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver


def test_candidate_service_file_resolves_exact_section_without_ambient_state(
    tmp_path: Path,
) -> None:
    """Read only caller-selected service-file authority and preserve exact values."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "# unrelated service\n"
        "[other]\n"
        "host=other.example\n"
        "\n"
        "[analytics]\n"
        "host=db.example\n"
        "port=6543\n"
        "dbname=batch queue\n"
        "user=batch user\n"
        "password=service-secret\n",
        encoding="utf-8",
    )

    resolver = Pg8000CandidateServiceFileResolver(service_file)

    assert resolver("analytics") == {
        "host": "db.example",
        "port": "6543",
        "dbname": "batch queue",
        "user": "batch user",
        "password": "service-secret",
    }


def test_candidate_service_file_rejects_missing_duplicate_or_empty_target(
    tmp_path: Path,
) -> None:
    """Fail closed when a service identity has no single authoritative stanza."""
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[analytics]\nhost=db.example\n[analytics]\nhost=other.example\n",
        encoding="utf-8",
    )
    resolver = Pg8000CandidateServiceFileResolver(service_file)

    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("analytics")
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("")
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver("missing")


def test_candidate_service_file_rejects_duplicate_keys_and_malformed_lines(
    tmp_path: Path,
) -> None:
    """Do not invent last-value-wins or permissive grammar for target authority."""
    duplicate_key = tmp_path / "duplicate.conf"
    duplicate_key.write_text(
        "[analytics]\nhost=db.example\nhost=other.example\n",
        encoding="utf-8",
    )
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(duplicate_key)("analytics")

    malformed = tmp_path / "malformed.conf"
    malformed.write_text("[analytics]\nhost db.example\n", encoding="utf-8")
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(malformed)("analytics")


def test_candidate_service_file_rejects_ldap_and_control_data(
    tmp_path: Path,
) -> None:
    """Keep network lookup and framed data outside the local candidate resolver."""
    ldap_file = tmp_path / "ldap.conf"
    ldap_file.write_text(
        "[analytics]\nldap://directory.example/dc=example?description?one?(cn=db)\n",
        encoding="utf-8",
    )
    with pytest.raises(
        Pg8000CandidateInvalidConninfoError,
        match="PostgreSQL connection selector is unsupported",
    ):
        Pg8000CandidateServiceFileResolver(ldap_file)("analytics")

    control_file = tmp_path / "control.conf"
    control_file.write_bytes(b"[analytics]\nhost=db.example\x00evil\n")
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(control_file)("analytics")


def test_candidate_service_file_rejects_non_utf8_or_oversized_input(
    tmp_path: Path,
) -> None:
    """Bound service metadata before decoding or parsing it."""
    invalid_utf8 = tmp_path / "invalid-utf8.conf"
    invalid_utf8.write_bytes(b"[analytics]\nhost=\xff\n")
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(invalid_utf8)("analytics")

    oversized = tmp_path / "oversized.conf"
    oversized.write_bytes(b"#" * 65_537)
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(oversized)("analytics")


def test_candidate_service_file_rejects_non_file_and_non_string_service(
    tmp_path: Path,
) -> None:
    """Normalize missing-file and invalid service identities at the candidate boundary."""
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        Pg8000CandidateServiceFileResolver(tmp_path / "missing.conf")("analytics")

    service_file = tmp_path / "pg_service.conf"
    service_file.write_text("[analytics]\nhost=db.example\n", encoding="utf-8")
    resolver = Pg8000CandidateServiceFileResolver(service_file)
    with pytest.raises(Pg8000CandidateInvalidConninfoError):
        resolver(7)  # type: ignore[arg-type]
