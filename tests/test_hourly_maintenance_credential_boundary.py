# SPDX-License-Identifier: Apache-2.0
"""Contracts for the hourly maintenance scheduler trust boundary."""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/hourly-maintenance.yml")
CENTRAL_SCHEDULER_SHA = "c47afc2dc68488292c1db7c9d6f82dcd5360f181"


def _job_block(workflow: str, job_name: str, next_job_name: str | None) -> str:
    """Return one exact top-level job block from the hourly workflow."""
    start = workflow.index(f"  {job_name}:\n")
    if next_job_name is None:
        return workflow[start:]
    end = workflow.index(f"  {next_job_name}:\n", start)
    return workflow[start:end]


def test_hourly_scheduler_preserves_cadence_without_cancelling_active_work() -> None:
    """A later hourly trigger must not cancel the maintenance run already executing."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'cron: "17 * * * *"' in workflow
    assert "group: hourly-commercial-maintenance-${{ github.repository }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "cancel-in-progress: true" not in workflow
    assert "queue:" not in workflow


def test_both_scheduler_calls_use_one_current_immutable_central_identity() -> None:
    """Repair and merge planes must consume the same protected central source."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert (
        "uses: ContextualWisdomLab/.github/.github/workflows/"
        f"pr-review-fix-scheduler.yml@{CENTRAL_SCHEDULER_SHA}"
        in workflow
    )
    assert (
        "uses: ContextualWisdomLab/.github/.github/workflows/"
        f"pr-review-merge-scheduler.yml@{CENTRAL_SCHEDULER_SHA}"
        in workflow
    )
    assert workflow.count(f"@{CENTRAL_SCHEDULER_SHA}") == 2
    assert "canonical_ref:" not in workflow


def test_review_fix_uses_oidc_without_forwarding_repository_secrets() -> None:
    """The repair caller grants OIDC but no stored repository mutation secret."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    review_fix = _job_block(workflow, "review-fix", "review-merge")

    assert "\n    permissions:\n" in review_fix
    permissions = review_fix.split("\n    permissions:\n", 1)[1].split("\n    uses:", 1)[0]
    permission_lines = {
        line.strip() for line in permissions.splitlines() if line.strip()
    }
    assert permission_lines == {"contents: read", "id-token: write"}
    assert "secrets:" not in review_fix
    assert "PR_REVIEW_MERGE_TOKEN" not in review_fix
    assert "OPENCODE_APPROVE_TOKEN" not in review_fix
    assert "COPILOT_GITHUB_TOKEN" not in review_fix
    assert "NVIDIA_NIM_API_KEY" not in review_fix


def test_merge_scheduler_keeps_reviewed_mutation_permissions_without_secrets() -> None:
    """The merge caller keeps bounded token permissions and relies on OIDC/App authority."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    review_merge = _job_block(workflow, "review-merge", None)

    required_permissions = {
        "actions: write",
        "checks: read",
        "contents: write",
        "id-token: write",
        "pull-requests: write",
    }
    permissions = review_merge.split("\n    permissions:\n", 1)[1].split(
        "\n    uses:", 1
    )[0]
    permission_lines = {
        line.strip() for line in permissions.splitlines() if line.strip()
    }
    assert permission_lines == required_permissions
    assert "secrets:" not in review_merge
    assert "merge_mode: direct_or_auto" in review_merge
    assert "enable_auto_merge: true" in review_merge
    assert "update_branches: true" in review_merge
