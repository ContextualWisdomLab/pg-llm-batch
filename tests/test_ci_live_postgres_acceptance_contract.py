# SPDX-License-Identifier: Apache-2.0
"""Contract tests for permanent live-PostgreSQL CI acceptance."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _workflow() -> str:
    """Read the repository CI workflow as executable contract text."""
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_runs_the_real_integration_marker_on_exact_pr_heads() -> None:
    """Permanent CI must execute the live PostgreSQL integration suite."""
    workflow = _workflow()

    assert "Build pg_tiktoken PostgreSQL integration image" in workflow
    assert "--target with-tiktoken" in workflow
    assert "Run live PostgreSQL integration suite" in workflow
    assert 'uv run pytest -q -m integration' in workflow
    assert "PG_LLM_BATCH_TEST_DSN" in workflow
    assert "docker run --detach" in workflow
    assert "docker inspect --format='{{json .State.Health.Status}}'" in workflow


def test_ci_live_fixture_uses_ephemeral_credential_authority_and_cleanup() -> None:
    """Live acceptance must keep database credentials ephemeral and off argv."""
    workflow = _workflow()

    assert "openssl rand -hex" in workflow
    assert "::add-mask::" in workflow
    assert "--env-file" in workflow
    assert "POSTGRES_PASSWORD=" in workflow
    assert "postgresql://pgllm:pgllm@" not in workflow
    assert "--env POSTGRES_PASSWORD=" not in workflow
    assert "Tear down live PostgreSQL integration fixture" in workflow
    assert "if: always()" in workflow
    assert "docker rm --force pg-llm-batch-postgres-integration" in workflow
