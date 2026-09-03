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


def _yaml_scalar_value(value: str) -> str:
    """Return one simple YAML scalar without a trailing inline comment."""
    normalized = value.strip()
    if " #" in normalized:
        normalized = normalized.split(" #", 1)[0].rstrip()
    return normalized


def _step_top_level_field(step: str, field: str) -> str | None:
    """Read one actual top-level workflow-step field, excluding comments."""
    lines = step.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if not first_line:
        return None
    base_indent = len(first_line) - len(first_line.lstrip())
    patterns = (
        re.compile(rf"^\s{{{base_indent}}}-\s+{re.escape(field)}:\s*(.*?)\s*$"),
        re.compile(rf"^\s{{{base_indent + 2}}}{re.escape(field)}:\s*(.*?)\s*$"),
    )

    for raw_line in lines:
        if raw_line.lstrip().startswith("#"):
            continue
        for pattern in patterns:
            match = pattern.match(raw_line)
            if match:
                return _yaml_scalar_value(match.group(1))
    return None


def _step_nested_field(step: str, mapping: str, field: str) -> str | None:
    """Read one direct child field from a workflow-step mapping."""
    lines = step.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    if not first_line:
        return None
    base_indent = len(first_line) - len(first_line.lstrip())
    mapping_indent = base_indent + 2
    field_indent = base_indent + 4
    in_mapping = False

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        if indent == mapping_indent and re.fullmatch(
            rf"{re.escape(mapping)}:\s*", stripped
        ):
            in_mapping = True
            continue
        if in_mapping and indent <= mapping_indent:
            in_mapping = False
        if not in_mapping or indent != field_indent:
            continue
        match = re.fullmatch(rf"{re.escape(field)}:\s*(.*?)\s*", stripped)
        if match:
            return _yaml_scalar_value(match.group(1))
    return None


def test_ci_workflow_enforces_supported_versions_and_quality_gates() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert 'python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]' in workflow
    assert "uv sync --locked" in workflow
    assert "uv run ruff check pg_llm_batch tests" in workflow
    assert "interrogate --fail-under 100 pg_llm_batch" in workflow
    assert "--cov-fail-under=100" in workflow
    assert "uv lock --check" in workflow
    assert "uv build --no-sources" in workflow
    assert "docker build --tag pg-llm-batch:ci ." in workflow
    assert "docker build --tag pg-llm-batch-postgres:ci docker/postgres" in workflow
    assert "Run legacy SQL cleanup integration smoke" in workflow
    assert "tests/smoke_legacy_sql_cleanup.sh" in workflow
    _assert_external_actions_are_pinned(workflow)


def test_ci_pg8000_candidate_parity_is_immutable_and_queue_conservative() -> None:
    """Keep replacement-driver proof exact without creating another runner lane."""
    workflow = _read(".github/workflows/ci.yml")
    project = _read("pyproject.toml")

    assert "pg8000-candidate-python314:" not in workflow
    assert "pg8000==1.31.5" in workflow
    assert (
        "0af2c1926b153307639868d2ee5cef6cd3a7d07448e12736989b10e1d491e201"
        in workflow
    )
    assert "tests/smoke_pg8000_candidate_postgres.py" in workflow
    assert "pg8000-candidate-ci-password" not in workflow
    assert "secrets.token_urlsafe(32)" in workflow
    assert "::add-mask::$candidate_password" in workflow
    assert "PG_LLM_BATCH_POSTGRES_PASSWORD=$candidate_password" in workflow
    assert "PG8000_CANDIDATE_PASSWORD_FILE" in workflow
    assert "Tear down candidate PostgreSQL runtime" in workflow
    assert '"pg8000' not in project


def test_workflow_step_field_matching_ignores_comments_and_unrelated_values() -> None:
    """Comment or nested text must not masquerade as workflow step fields."""
    decoy = """      - name: Decoy
        # uses: actions/checkout@0000000000000000000000000000000000000000
        # persist-credentials: false
        env:
          NOTE: uses: actions/checkout@0000000000000000000000000000000000000000
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          persist-credentials: false
        run: echo 'uses: actions/checkout@0000000000000000000000000000000000000000'
"""

    assert _step_top_level_field(decoy, "uses") is None
    assert _step_nested_field(decoy, "with", "ref") is None
    assert _step_nested_field(decoy, "with", "persist-credentials") is None


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
            uses = _step_top_level_field(step, "uses")
            if uses is None or not uses.startswith("actions/checkout@"):
                continue
            checkout_count += 1
            assert _step_nested_field(step, "with", "ref") == exact_source_expression
            assert _step_nested_field(step, "with", "persist-credentials") == "false"
            assert index + 1 < len(steps)
            verification_step = steps[index + 1]
            assert _step_top_level_field(verification_step, "name") == (
                "Verify exact source head"
            )
            assert _step_top_level_field(verification_step, "run") == exact_verification

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
