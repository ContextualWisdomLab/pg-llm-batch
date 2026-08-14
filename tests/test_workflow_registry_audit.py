"""Regression tests for the read-only workflow registry audit tool."""

from __future__ import annotations

import io
import json
import traceback
from dataclasses import dataclass
from urllib.error import HTTPError

import pytest

from workflow_registry_audit import (
    GitHubReadClient,
    WorkflowRegistryAuditError,
    audit_repository_workflows,
)


PROTECTED_SHA = "d0a4b30be1f46536e352443309f3a35533156767"
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
        self.requested_paths: list[str] = []

    def get_json(self, path: str) -> dict[str, object]:
        """Return the next payload only when the exact expected path matches."""
        self.requested_paths.append(path)
        if not self._routes:
            raise AssertionError(f"unexpected GitHub read: {path}")
        route = self._routes.pop(0)
        assert path.endswith(route.suffix)
        return route.payload


def _tree_payload(*paths: str, truncated: bool = False) -> dict[str, object]:
    return {
        "sha": PROTECTED_SHA,
        "truncated": truncated,
        "tree": [
            {"path": path, "type": "blob", "sha": f"blob-{index}"}
            for index, path in enumerate(paths, start=1)
        ],
    }


def _workflow(workflow_id: int, path: str, state: str = "active") -> dict[str, object]:
    return {
        "id": workflow_id,
        "path": path,
        "state": state,
        "name": f"workflow-{workflow_id}",
    }


def test_exact_path_presence_drives_classification_not_workflow_name() -> None:
    """One-shot-like names stay safe when their exact protected path exists."""
    client = _FakeClient(
        [
            _JsonRoute(
                f"/git/trees/{PROTECTED_SHA}?recursive=1",
                _tree_payload(
                    ".github/workflows/ci.yml",
                    ".github/workflows/one-shot-legitimate.yml",
                ),
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=1",
                {
                    "total_count": 4,
                    "workflows": [
                        _workflow(1, ".github/workflows/ci.yml"),
                        _workflow(2, ".github/workflows/deleted-one-shot.yml"),
                        _workflow(3, ".github/workflows/one-shot-legitimate.yml"),
                        _workflow(4, ".github/workflows/CI.yml", state="disabled_manually"),
                    ],
                },
            ),
        ]
    )

    receipt = audit_repository_workflows(
        repository_full_name=REPOSITORY,
        protected_sha=PROTECTED_SHA,
        client=client,
        captured_at=CAPTURED_AT,
    )

    assert receipt["protected_sha"] == PROTECTED_SHA
    assert receipt["captured_at"] == CAPTURED_AT
    assert receipt["pages_scanned"] == 1
    assert receipt["registry_total_count"] == 4
    assert receipt["active_absent_workflows"] == [
        {
            "workflow_id": 2,
            "path": ".github/workflows/deleted-one-shot.yml",
            "state": "active",
        }
    ]
    records = {item["workflow_id"]: item for item in receipt["workflow_records"]}
    assert records[1]["source_present"] is True
    assert records[3]["source_present"] is True
    assert records[4]["source_present"] is False


def test_registry_pagination_is_complete_and_receipted() -> None:
    """The detector reads every page required by the first stable total count."""
    first_page = [
        _workflow(index, f".github/workflows/old-{index}.yml", state="disabled_manually")
        for index in range(1, 101)
    ]
    second_page = [_workflow(101, ".github/workflows/ci.yml")]
    client = _FakeClient(
        [
            _JsonRoute(
                f"/git/trees/{PROTECTED_SHA}?recursive=1",
                _tree_payload(".github/workflows/ci.yml"),
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=1",
                {"total_count": 101, "workflows": first_page},
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=2",
                {"total_count": 101, "workflows": second_page},
            ),
        ]
    )

    receipt = audit_repository_workflows(
        repository_full_name=REPOSITORY,
        protected_sha=PROTECTED_SHA,
        client=client,
        captured_at=CAPTURED_AT,
    )

    assert receipt["pages_scanned"] == 2
    assert receipt["registry_total_count"] == 101
    assert len(receipt["workflow_records"]) == 101
    assert receipt["active_absent_workflows"] == []


def test_incomplete_pagination_fails_closed() -> None:
    """An empty page before the advertised total is not accepted as complete."""
    client = _FakeClient(
        [
            _JsonRoute(
                f"/git/trees/{PROTECTED_SHA}?recursive=1",
                _tree_payload(".github/workflows/ci.yml"),
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=1",
                {"total_count": 101, "workflows": [_workflow(1, ".github/workflows/ci.yml")]},
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=2",
                {"total_count": 101, "workflows": []},
            ),
        ]
    )

    with pytest.raises(WorkflowRegistryAuditError, match="pagination is incomplete"):
        audit_repository_workflows(
            repository_full_name=REPOSITORY,
            protected_sha=PROTECTED_SHA,
            client=client,
            captured_at=CAPTURED_AT,
        )


def test_registry_change_during_pagination_fails_closed() -> None:
    """A moving registry cannot be presented as one coherent audit receipt."""
    client = _FakeClient(
        [
            _JsonRoute(
                f"/git/trees/{PROTECTED_SHA}?recursive=1",
                _tree_payload(".github/workflows/ci.yml"),
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=1",
                {
                    "total_count": 101,
                    "workflows": [
                        _workflow(index, f".github/workflows/old-{index}.yml", "disabled_manually")
                        for index in range(1, 101)
                    ],
                },
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=2",
                {"total_count": 102, "workflows": [_workflow(101, ".github/workflows/ci.yml")]},
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


def test_duplicate_workflow_id_fails_closed() -> None:
    """A reused ID with ambiguous path/state cannot be silently normalized."""
    client = _FakeClient(
        [
            _JsonRoute(
                f"/git/trees/{PROTECTED_SHA}?recursive=1",
                _tree_payload(".github/workflows/ci.yml"),
            ),
            _JsonRoute(
                "/actions/workflows?per_page=100&page=1",
                {
                    "total_count": 2,
                    "workflows": [
                        _workflow(7, ".github/workflows/ci.yml"),
                        _workflow(7, ".github/workflows/old.yml"),
                    ],
                },
            ),
        ]
    )

    with pytest.raises(WorkflowRegistryAuditError, match="duplicate workflow id"):
        audit_repository_workflows(
            repository_full_name=REPOSITORY,
            protected_sha=PROTECTED_SHA,
            client=client,
            captured_at=CAPTURED_AT,
        )


def test_truncated_protected_tree_fails_closed() -> None:
    """A partial protected tree is not evidence that a workflow source is absent."""
    client = _FakeClient(
        [
            _JsonRoute(
                f"/git/trees/{PROTECTED_SHA}?recursive=1",
                _tree_payload(".github/workflows/ci.yml", truncated=True),
            )
        ]
    )

    with pytest.raises(WorkflowRegistryAuditError, match="protected tree is truncated"):
        audit_repository_workflows(
            repository_full_name=REPOSITORY,
            protected_sha=PROTECTED_SHA,
            client=client,
            captured_at=CAPTURED_AT,
        )


def test_invalid_sha_is_rejected_before_any_github_read() -> None:
    """A mutable branch name cannot masquerade as exact protected-head evidence."""
    client = _FakeClient([])

    with pytest.raises(WorkflowRegistryAuditError, match="exact 40-hex protected SHA"):
        audit_repository_workflows(
            repository_full_name=REPOSITORY,
            protected_sha="main",
            client=client,
            captured_at=CAPTURED_AT,
        )

    assert client.requested_paths == []


def test_http_failure_does_not_retain_lower_layer_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    """403/404/5xx-style transport details remain outside rendered evidence."""
    secret_sentinel = "SECRET_HTTP_DIAGNOSTIC_SHOULD_NOT_ESCAPE"

    def _raise_http_error(*_args: object, **_kwargs: object) -> object:
        raise HTTPError(
            "https://api.github.com/private?token=secret",
            503,
            secret_sentinel,
            hdrs=None,
            fp=io.BytesIO(json.dumps({"message": secret_sentinel}).encode()),
        )

    monkeypatch.setattr("workflow_registry_audit.urlopen", _raise_http_error)
    client = GitHubReadClient(token="token-value-that-must-not-render")

    try:
        client.get_json(f"/repos/{REPOSITORY}/actions/workflows?per_page=100&page=1")
    except WorkflowRegistryAuditError as exc:
        rendered = "".join(traceback.format_exception(exc))
        assert str(exc) == "GitHub workflow audit read failed"
        assert secret_sentinel not in rendered
        assert "token-value-that-must-not-render" not in rendered
        assert exc.__cause__ is None
        assert exc.__suppress_context__ is True
    else:
        raise AssertionError("expected WorkflowRegistryAuditError")
