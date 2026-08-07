# SPDX-License-Identifier: Apache-2.0
"""CI contract for the live checkpoint-audit PostgreSQL verification gate."""

from pathlib import Path


def test_ci_runs_checkpoint_audit_against_ephemeral_postgres() -> None:
    """CI must execute the audit integration test against pinned PostgreSQL."""
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    ).read_text(encoding="utf-8")
    required = (
        "checkpoint-audit-integration:",
        "name: Checkpoint audit PostgreSQL integration",
        "postgres:16-bookworm@sha256:da788743d2060767375896de4d646f7576f5911461444b372616f19ea61db2ec",
        "PG_LLM_BATCH_TEST_DSN: postgresql://postgres:postgres@localhost:5432/postgres",
        "persist-credentials: false",
        "uv run pytest -q tests/test_checkpoint_audit_integration.py -m integration",
    )
    for phrase in required:
        assert phrase in workflow
