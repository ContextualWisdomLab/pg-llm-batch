"""Live-registry regressions for platform-managed dynamic workflow identities."""

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
    """Serve exact ordered GitHub responses for dynamic-workflow tests."""

    def __init__(self, routes: list[_Route]) -> None:
        self._routes = list(routes)

    def get_json(self, path: str) -> dict[str, object]:
        """Return the next expected response and reject unexpected reads."""
        if not self._routes:
            raise AssertionError(f"unexpected GitHub read: {path}")
        route = self._routes.pop(0)
        assert path.endswith(route.suffix)
        return route.payload


def test_dynamic_platform_workflow_is_receipted_but_never_an_orphan_candidate() -> None:
    """GitHub-managed dynamic identities cannot be mistaken for deleted YAML."""
    repository_path = ".github/workflows/deleted-one-shot.yml"
    dynamic_path = "dynamic/github-code-scanning/codeql"
    client = _FakeClient(
        [
            _Route(
                f"/git/commits/{PROTECTED_SHA}",
                {"sha": PROTECTED_SHA, "tree": {"sha": TREE_SHA}},
            ),
            _Route(
                f"/git/trees/{TREE_SHA}?recursive=1",
                {"sha": TREE_SHA, "truncated": False, "tree": []},
            ),
            _Route(
                "/actions/workflows?per_page=100&page=1",
                {
                    "total_count": 2,
                    "workflows": [
                        {"id": 7, "path": repository_path, "state": "active"},
                        {"id": 8, "path": dynamic_path, "state": "active"},
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

    records = {record["workflow_id"]: record for record in receipt["workflow_records"]}
    assert records[7] == {
        "workflow_id": 7,
        "path": repository_path,
        "state": "active",
        "source_kind": "repository",
        "source_present": False,
    }
    assert records[8] == {
        "workflow_id": 8,
        "path": dynamic_path,
        "state": "active",
        "source_kind": "platform_dynamic",
        "source_present": None,
    }
    assert receipt["active_absent_workflows"] == [
        {"workflow_id": 7, "path": repository_path, "state": "active"}
    ]
