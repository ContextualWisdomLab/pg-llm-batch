# SPDX-License-Identifier: Apache-2.0
"""Contract tests asserting CI workflow governance invariants (SHA pinning, gates)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    """Read one repository-relative text file used by a workflow contract."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _assert_external_actions_are_pinned(workflow: str) -> None:
    """Require every action and reusable workflow to use an immutable SHA."""
    for raw_line in workflow.splitlines():
        line = raw_line.strip()
        if not line.startswith("uses:"):
            continue
        target = line.removeprefix("uses:").strip()
        assert re.search(r"@[0-9a-f]{40}(?:\s|$)", target), target


def _workflow_job_steps(workflow: str) -> list[list[str]]:
    """Return raw step blocks for every top-level job in a workflow."""
    job_steps: list[list[str]] = []
    current_steps: list[str] | None = None
    current_step_lines: list[str] | None = None
    inside_steps = False

    for raw_line in workflow.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip())

        if indent == 2 and stripped.endswith(":") and not stripped.startswith("-"):
            inside_steps = False
            current_steps = None
            current_step_lines = None
            continue

        if indent == 4 and stripped == "steps:":
            current_steps = []
            job_steps.append(current_steps)
            current_step_lines = None
            inside_steps = True
            continue

        if not inside_steps:
            continue

        if indent == 6 and stripped.startswith("- "):
            current_step_lines = [raw_line]
            assert current_steps is not None
            current_steps.append("\n".join(current_step_lines))
            continue

        if stripped and indent <= 4:
            inside_steps = False
            current_steps = None
            current_step_lines = None
            continue

        if current_step_lines is not None:
            current_step_lines.append(raw_line)
            assert current_steps is not None
            current_steps[-1] = "\n".join(current_step_lines)

    return job_steps


def test_ci_workflow_enforces_supported_versions_and_quality_gates() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert 'python-version: ["3.10", "3.12", "3.14"]' in workflow
    assert "uv sync --locked" in workflow
    assert "uv run ruff check pg_llm_batch tests" in workflow
    assert "interrogate --fail-under 100 pg_llm_batch" in workflow
    assert "--cov-fail-under=100" in workflow
    assert "uv lock --check" in workflow
    assert "uv build --no-sources" in workflow
    assert "docker build --tag pg-llm-batch:ci ." in workflow
    assert "docker build --tag pg-llm-batch-postgres:ci docker/postgres" in workflow
    _assert_external_actions_are_pinned(workflow)


def test_ci_checks_out_and_verifies_the_exact_source_head_in_every_job() -> None:
    """Every CI checkout must bind and verify the exact source head."""
    workflow = _read(".github/workflows/ci.yml")
    exact_source_expression = "${{ github.event.pull_request.head.sha || github.sha }}"
    exact_verification = (
        f'test "$(git rev-parse HEAD)" = "{exact_source_expression}"'
    )
    checkout_count = 0

    for steps in _workflow_job_steps(workflow):
        for index, step in enumerate(steps):
            if "uses: actions/checkout@" not in step:
                continue
            checkout_count += 1
            assert f"ref: {exact_source_expression}" in step
            assert index + 1 < len(steps)
            verification_step = steps[index + 1]
            assert "- name: Verify exact source head" in verification_step
            assert exact_verification in verification_step

    assert checkout_count > 0


def test_hourly_workflow_repairs_revalidates_and_merges_pull_requests() -> None:
    workflow = _read(".github/workflows/hourly-maintenance.yml")
    scheduler_sha = "5983b41ace75040c1d81818171ca7d0f3653254e"

    assert 'cron: "17 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert (
        "uses: ContextualWisdomLab/.github/.github/workflows/"
        "pr-review-fix-scheduler.yml@"
    ) in workflow
    assert "target_repository: ContextualWisdomLab/pg-llm-batch" in workflow
    assert 'retry_hours: "1"' in workflow
    assert f"canonical_ref: {scheduler_sha}" in workflow
    assert (
        "uses: ContextualWisdomLab/.github/.github/workflows/"
        "pr-review-merge-scheduler.yml@"
    ) in workflow
    assert "merge_mode: direct_or_auto" in workflow
    assert "trigger_reviews: true" in workflow
    assert "enable_auto_merge: true" in workflow
    assert "update_branches: true" in workflow
    assert workflow.count(f"@{scheduler_sha}") == 2
    _assert_external_actions_are_pinned(workflow)


def test_dependabot_tracks_the_new_github_actions_manifests() -> None:
    configuration = _read(".github/dependabot.yml")

    assert 'package-ecosystem: "github-actions"' in configuration
    assert 'directory: "/"' in configuration
    assert 'interval: "weekly"' in configuration
    assert "dependency_file_not_found" not in configuration


def test_pyproject_declares_hard_quality_thresholds() -> None:
    config = _read("pyproject.toml")

    assert '[tool.coverage.run]\nsource = ["pg_llm_batch"]' in config
    assert '[tool.coverage.report]\nfail_under = 100\nshow_missing = true' in config
    assert '[tool.interrogate]\nexclude = ["tests"]\nfail-under = 100' in config
