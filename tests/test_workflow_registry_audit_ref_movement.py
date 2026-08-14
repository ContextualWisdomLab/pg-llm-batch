"""Protected-ref movement regressions for the workflow registry audit."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from workflow_registry_audit import (
    WorkflowRegistryAuditError,
    audit_live_protected_ref_workflows,
)


PROTECTED_SHA = "d0a4b30be1f46536e352443309f3a35533156767"
TREE_SHA = "61e02626f1184dede4990f06704574e878012336"
MOVED_SHA = "f" * 40
REPOSITORY = "ContextualWisdomLab/pg-llm-batch"


@dataclass
class _Route:
    """Describe one exact fake GitHub read."""

    suffix: str
    payload: dict[str, object]


class _FakeClient:
    """Serve exact ordered GitHub responses for ref movement tests."""

    def __init__(self, routes: list[_Route]) -> None:
        self._routes = list(routes)

    def get_json(self, path: str) -> dict[str, object]:
        """Return the next expected response and reject unexpected reads."""
        if not self._routes:
            raise AssertionError(f"unexpected GitHub read: {path}")
        route = self._routes.pop(0)
        assert path.endswith(route.suffix)
        return route.payload


def _ref_payload(sha: str) -> dict[str, object]:
    return {"ref": "refs/heads/main", "object": {"sha": sha, "type": "commit"}}


def _commit_payload() -> dict[str, object]:
    """Return the protected commit with a distinct recursive-tree identity."""
    return {"sha": PROTECTED_SHA, "tree": {"sha": TREE_SHA}}


def _tree_payload() -> dict[str, object]:
    """Return the tree object referenced by the protected commit."""
    return {"sha": TREE_SHA, "truncated": False, "tree": []}


def test_initial_protected_ref_mismatch_fails_before_tree_or_registry_reads() -> None:
    """A supplied stale protected SHA cannot be certified as live main evidence."""
    client = _FakeClient([_Route("/git/ref/heads/main", _ref_payload(MOVED_SHA))])

    with pytest.raises(WorkflowRegistryAuditError, match="does not match expected SHA"):
        audit_live_protected_ref_workflows(
            repository_full_name=REPOSITORY,
            protected_ref="main",
            expected_protected_sha=PROTECTED_SHA,
            client=client,
        )


def test_protected_ref_movement_during_registry_scan_fails_closed() -> None:
    """A main-branch move during pagination invalidates the entire audit receipt."""
    client = _FakeClient(
        [
            _Route("/git/ref/heads/main", _ref_payload(PROTECTED_SHA)),
            _Route(f"/git/commits/{PROTECTED_SHA}", _commit_payload()),
            _Route(f"/git/trees/{TREE_SHA}?recursive=1", _tree_payload()),
            _Route(
                "/actions/workflows?per_page=100&page=1",
                {"total_count": 0, "workflows": []},
            ),
            _Route("/git/ref/heads/main", _ref_payload(MOVED_SHA)),
        ]
    )

    with pytest.raises(WorkflowRegistryAuditError, match="moved during audit"):
        audit_live_protected_ref_workflows(
            repository_full_name=REPOSITORY,
            protected_ref="main",
            expected_protected_sha=PROTECTED_SHA,
            client=client,
        )
