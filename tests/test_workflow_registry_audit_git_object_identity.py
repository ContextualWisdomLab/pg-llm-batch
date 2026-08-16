"""Git-object identity regression for the workflow registry audit."""

from __future__ import annotations

from dataclasses import dataclass

from pg_llm_batch.workflow_registry_audit import audit_repository_workflows


PROTECTED_SHA = "d0a4b30be1f46536e352443309f3a35533156767"
TREE_SHA = "61e02626f1184dede4990f06704574e878012336"
REPOSITORY = "ContextualWisdomLab/pg-llm-batch"


@dataclass
class _Route:
    """Describe one exact fake GitHub read."""

    suffix: str
    payload: dict[str, object]


class _FakeClient:
    """Require the documented commit-to-tree lookup sequence."""

    def __init__(self, routes: list[_Route]) -> None:
        self._routes = list(routes)
        self.requested_paths: list[str] = []

    def get_json(self, path: str) -> dict[str, object]:
        """Return only the next exact response and record every request."""
        self.requested_paths.append(path)
        route = self._routes.pop(0)
        assert path.endswith(route.suffix)
        return route.payload


def test_protected_commit_is_resolved_to_its_tree_before_recursive_read() -> None:
    """The audit must not treat a commit object SHA as a tree object SHA."""
    client = _FakeClient(
        [
            _Route(
                f"/git/commits/{PROTECTED_SHA}",
                {"sha": PROTECTED_SHA, "tree": {"sha": TREE_SHA}},
            ),
            _Route(
                f"/git/trees/{TREE_SHA}?recursive=1",
                {
                    "sha": TREE_SHA,
                    "truncated": False,
                    "tree": [{"path": ".github/workflows/ci.yml", "type": "blob"}],
                },
            ),
            _Route(
                "/actions/workflows?per_page=100&page=1",
                {
                    "total_count": 1,
                    "workflows": [
                        {
                            "id": 1,
                            "path": ".github/workflows/ci.yml",
                            "state": "active",
                        }
                    ],
                },
            ),
        ]
    )

    receipt = audit_repository_workflows(
        repository_full_name=REPOSITORY,
        protected_sha=PROTECTED_SHA,
        client=client,
        captured_at="2026-08-15T00:00:00Z",
    )

    assert receipt["active_absent_workflows"] == []
    assert client.requested_paths[:2] == [
        f"/repos/{REPOSITORY}/git/commits/{PROTECTED_SHA}",
        f"/repos/{REPOSITORY}/git/trees/{TREE_SHA}?recursive=1",
    ]
