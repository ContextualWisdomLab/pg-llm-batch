# SPDX-License-Identifier: Apache-2.0
"""Contracts for the hourly maintenance scheduler credential boundary."""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/hourly-maintenance.yml")
ADR_PATH = Path("docs/adr/0013-hourly-maintenance-credential-boundary.md")
FIX_SCHEDULER_SHA = "afd33b5d09f331f2b73913c1d4b312be9296a449"
MERGE_SCHEDULER_SHA = "5983b41ace75040c1d81818171ca7d0f3653254e"


def _job_block(workflow: str, job_name: str, next_job_name: str | None) -> str:
    """Return one exact top-level job block from the hourly workflow."""
    start = workflow.index(f"  {job_name}:\n")
    if next_job_name is None:
        return workflow[start:]
    end = workflow.index(f"  {next_job_name}:\n", start)
    return workflow[start:end]


def _top_level_concurrency_block(workflow: str) -> str:
    """Return the workflow-level concurrency block before permissions."""
    start = workflow.index("concurrency:\n")
    end = workflow.index("\npermissions:\n", start)
    return workflow[start:end]


def _normalized_document(path: Path) -> str:
    """Return one Markdown contract with layout-only whitespace normalized."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_hourly_scheduler_queues_single_flight_instead_of_cancelling_recovery() -> None:
    """A later hourly trigger cannot cancel an active diagnosis or repair run."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    concurrency = _top_level_concurrency_block(workflow)

    assert "group: hourly-commercial-maintenance-${{ github.repository }}" in concurrency
    assert "cancel-in-progress: false" in concurrency
    assert "queue: max" in concurrency
    assert "cancel-in-progress: true" not in concurrency


def test_hourly_scheduler_documents_rca_feasibility_and_scoped_lease_recovery() -> None:
    """The operator contract turns blockers into bounded action rather than broad stops."""
    contract = _normalized_document(ADR_PATH)

    required_contracts = (
        "root-cause analysis → candidate remedy → feasibility check → execution",
        "same `pg-llm-batch` target branch, pull request, or target blob",
        "read-only dependency movement",
        "does not create a repository-wide writer-lease conflict",
        "permissions, branch protection, exact-head checks, dependency integration, blast radius, and rollback",
        "continue unrelated safe work",
    )
    for required_contract in required_contracts:
        assert required_contract in contract


def test_review_fix_uses_immutable_current_central_scheduler() -> None:
    """The repair job pins the reviewed central scheduler prerequisite exactly."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    review_fix = _job_block(workflow, "review-fix", "review-merge")

    assert (
        "uses: ContextualWisdomLab/.github/.github/workflows/"
        f"pr-review-fix-scheduler.yml@{FIX_SCHEDULER_SHA}"
        in review_fix
    )
    assert f"canonical_ref: {FIX_SCHEDULER_SHA}" in review_fix
    assert f"@{MERGE_SCHEDULER_SHA}" not in review_fix


def test_review_fix_never_elevates_or_inherits_workflow_token() -> None:
    """Repair mutation uses only explicit established secrets, not GITHUB_TOKEN."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    review_fix = _job_block(workflow, "review-fix", "review-merge")

    assert "\n    permissions:\n" not in review_fix
    assert "secrets: inherit" not in review_fix
    assert (
        "PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}"
        in review_fix
    )
    assert (
        "OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}"
        in review_fix
    )
    assert "COPILOT_GITHUB_TOKEN" not in review_fix
    assert "NVIDIA_NIM_API_KEY" not in review_fix


def test_merge_scheduler_contract_is_unchanged_by_repair_hardening() -> None:
    """The independent merge plane retains its existing reviewed credential chain."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    review_merge = _job_block(workflow, "review-merge", None)

    assert (
        "uses: ContextualWisdomLab/.github/.github/workflows/"
        f"pr-review-merge-scheduler.yml@{MERGE_SCHEDULER_SHA}"
        in review_merge
    )
    assert "secrets: inherit" in review_merge
    assert "merge_mode: direct_or_auto" in review_merge
    assert "enable_auto_merge: true" in review_merge
