"""Adversarial stability regressions for workflow registry pagination."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from workflow_registry_audit import WorkflowRegistryAuditError, audit_repository_workflows


PROTECTED_SHA = "d0a4b30be1f46536e352443309f3a35533156767"
TREE_SHA = "61e02626f1184dede4990f06704574e878012336"
REPOSITORY = "ContextualWisdomLab/pg-llm-batch"
CAPTURED_AT = "2026-08-15T00:00:00Z"


@dataclass
class _JsonRoute:
    """Describe one expected fake GitHub JSON response."""

    suffix: str
    payload: dict[str, object]


class _FakeClient:
    """Serve deterministic GitHub API payloads while recording exact reads."""

    def __init__(self, routes: list[_JsonRoute]) -> None:
        self._routes = list(routes)

    def get_json(self, path: str) -> dict[str, object]:
        """Return the next payload only for the exact expected request suffix."""
        if not self._routes:
            raise AssertionError(f"unexpected GitHub read: {path}")
        route = self._routes.pop(0)
        assert path.endswith(route.suffix)
        return route.payload


def _workflow(workflow_id: int, *, state: str = "disabled_manually") -> dict[str, object]:
    """Return one deterministic workflow-registry record."""
    return {
        "id": workflow_id,
        "path": f".github/workflows/workflow-{workflow_id}.yml",
        "state": state,
    }


def test_same_count_page_shift_is_not_accepted_as_stable_registry() -> None:
    """A same-cardinality delete/add between pages must invalidate the receipt.

    The first pagination pass can otherwise contain 1..100 from the old registry
    plus 102 from the new registry: 101 unique rows with an unchanged total_count,
    but not one coherent registry state. A stable verification pass observes the
    actual new set 2..102 and must make the audit fail closed.
    """
    first_page_before_shift = [_workflow(workflow_id) for workflow_id in range(1, 101)]
    second_page_after_shift = [_workflow(102, state="active")]
    stable_new_first_page = [_workflow(workflow_id) for workflow_id in range(2, 102)]
    stable_new_second_page = [_workflow(102, state="active")]
    client = _FakeClient(
        [
            _JsonRoute(
                f"/git/commits/{PROTECTED_SHA}",
                {"sha": PROTECTED_SHA, "tree": {"sha": TREE_SHA}},
            ),
            _JsonRoute(
                f"/git/trees/{TREE_SHA}?recursive=1",
                {
                    "sha": TREE_SHA,
                    "truncated": False,
                    "tree": [],
                },
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=1",
                {"total_count": 101, "workflows": first_page_before_shift},
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=2",
                {"total_count": 101, "workflows": second_page_after_shift},
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=1",
                {"total_count": 101, "workflows": stable_new_first_page},
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=2",
                {"total_count": 101, "workflows": stable_new_second_page},
            ),
        ]
    )

    with pytest.raises(WorkflowRegistryAuditError, match="changed during audit"):
        audit_repository_workflows(
            repository_full_name=REPOSITORY,
            protected_sha=PROTECTED_SHA,
            client=client,
            captured_at=CAPTURED_AT,
        )
