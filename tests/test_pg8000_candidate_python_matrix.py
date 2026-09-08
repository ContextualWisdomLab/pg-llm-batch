"""Regression for exact-artifact pg8000 parity across shipped Python runtimes."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_real_pg8000_postgres_smoke_covers_release_runtime_matrix() -> None:
    """Run the installed package plus real candidate/PostgreSQL contract per minor."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    expected_runtimes = {
        "3.10": "/tmp/pg8000-candidate-py310/bin/python",
        "3.12": "/tmp/pg8000-candidate-py312/bin/python",
        "3.14": "/tmp/pg8000-candidate-py314/bin/python",
    }
    assert "Build exact pg-llm-batch wheel for candidate parity" in workflow
    assert "uv build --wheel --no-sources" in workflow
    assert "/tmp/pg-llm-batch-candidate-wheel" in workflow
    assert "Install exact pg-llm-batch wheel into candidate environments" in workflow

    for python_version, interpreter in expected_runtimes.items():
        assert f'python-version: "{python_version}"' in workflow
        assert f'uv pip install --python "{interpreter}" --no-deps' in workflow
        assert f"uv pip check --python {interpreter}" in workflow
        assert f'cd "$RUNNER_TEMP" && {interpreter} ' in workflow
        assert '"$GITHUB_WORKSPACE/tests/smoke_pg8000_candidate_postgres.py"' in workflow

    assert "PYTHONPATH=." not in workflow
    assert workflow.count("tests/smoke_pg8000_candidate_postgres.py") == len(
        expected_runtimes
    )
