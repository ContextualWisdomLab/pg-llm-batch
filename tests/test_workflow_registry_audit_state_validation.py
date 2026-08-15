"""Regression tests for fail-closed GitHub workflow-state evidence."""

from __future__ import annotations

from typing import Any

import pytest

from workflow_registry_audit import WorkflowRegistryAuditError, audit_repository_workflows


PROTECTED_SHA = "d0a4b30be1f46536e352443309f3a35533156767"
TREE_SHA = "61e02626f1184dede4990f06704574e878012336"
REPOSITORY = "ContextualWisdomLab/pg-llm-batch"


class _FakeClient:
    """Return exact GitHub commit, tree, and registry payloads in sequence."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def get_json(self, path: str) -> dict[str, Any]:
        """Serve one deterministic response for each expected audit read."""
        self.paths.append(path)
        if path.endswith(f"/git/commits/{PROTECTED_SHA}"):
            return {"sha": PROTECTED_SHA, "tree": {"sha": TREE_SHA}}
        if path.endswith(f"/git/trees/{TREE_SHA}?recursive=1"):
            return {"sha": TREE_SHA, "truncated": False, "tree": []}
        if path.endswith("/actions/workflows?per_page=100&page=1"):
            return {
                "total_count": 1,
                "workflows": [
                    {
                        "id": 17,
                        "path": ".github/workflows/removed.yml",
                        "state": "future_unknown_state",
                    }
                ],
            }
        raise AssertionError(f"unexpected path: {path}")


def test_unknown_workflow_state_fails_closed_instead_of_suppressing_candidate() -> None:
    """Unrecognized registry state must not silently become non-active evidence."""
    client = _FakeClient()

    with pytest.raises(WorkflowRegistryAuditError, match="record is invalid"):
        audit_repository_workflows(
            repository_full_name=REPOSITORY,
            protected_sha=PROTECTED_SHA,
            client=client,
            captured_at="2026-08-15T00:00:00Z",
        )

    assert len(client.paths) == 3
