# SPDX-License-Identifier: Apache-2.0
"""Protect the pg8000 candidate smoke credential from duplicate env propagation."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    """Read one repository-owned candidate acceptance artifact."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_pg8000_candidate_credential_uses_only_ephemeral_password_file() -> None:
    """Keep the candidate password in one masked file boundary, not GITHUB_ENV."""
    workflow = _read(".github/workflows/ci.yml")
    smoke = _read("tests/smoke_pg8000_candidate_postgres.py")

    assert "PG8000_CANDIDATE_PASSWORD_FILE=$password_file" in workflow
    assert "PG_LLM_BATCH_POSTGRES_PASSWORD=$candidate_password" not in workflow
    assert 'os.environ.get("PG_LLM_BATCH_POSTGRES_PASSWORD")' not in smoke
    assert 'os.environ.get("PG8000_CANDIDATE_PASSWORD_FILE")' in smoke
    assert ".read_text(encoding=\"utf-8\")" in smoke
