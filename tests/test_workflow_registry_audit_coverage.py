# SPDX-License-Identifier: Apache-2.0
"""Remaining fail-closed branches for the packaged workflow registry audit."""

from __future__ import annotations

import asyncio

import pytest

from pg_llm_batch.workflow_registry_audit import (
    GitHubReadClient,
    WorkflowRegistryAuditError,
    _read_registry,
    _validate_workflow_record,
    audit_live_protected_ref_workflows,
    audit_repository_workflows,
)

_PROTECTED_SHA = "a" * 40
_TREE_SHA = "b" * 40
_REPOSITORY = "ContextualWisdomLab/pg-llm-batch"


class _StaticClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses

    def get_json(self, path: str) -> object:
        return self._responses[path]


def _commit_and_tree(*, tree_entries: list[object] | None = None) -> dict[str, object]:
    return {
        f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}": {
            "sha": _PROTECTED_SHA,
            "tree": {"sha": _TREE_SHA.upper()},
        },
        f"/repos/{_REPOSITORY}/git/trees/{_TREE_SHA}?recursive=1": {
            "sha": _TREE_SHA,
            "truncated": False,
            "tree": [] if tree_entries is None else tree_entries,
        },
        f"/repos/{_REPOSITORY}/actions/workflows?per_page=100&page=1": {
            "total_count": 0,
            "workflows": [],
        },
    }


def test_sync_client_rejects_an_active_event_loop() -> None:
    """Operators cannot hide the sync client inside another running loop."""

    async def _invoke() -> None:
        with pytest.raises(WorkflowRegistryAuditError, match="active event loop"):
            GitHubReadClient().get_json(f"/repos/{_REPOSITORY}/actions/workflows")

    asyncio.run(_invoke())


def test_decoded_non_object_json_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JSON array is not a GitHub object receipt."""

    class _Content:
        async def iter_chunked(self, _size: int):
            yield b"[]"

    class _Response:
        status = 200
        headers: dict[str, str] = {}
        content_length = 2
        content = _Content()

        async def __aenter__(self) -> "_Response":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _Session:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def get(self, _path: str, *, allow_redirects: bool) -> _Response:
            assert allow_redirects is False
            return _Response()

    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession",
        _Session,
    )
    with pytest.raises(WorkflowRegistryAuditError, match="response is invalid"):
        GitHubReadClient().get_json(f"/repos/{_REPOSITORY}/actions/workflows")


def test_response_stream_must_expose_chunk_iterator(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response without iter_chunked cannot be materialized unsafely."""

    class _Response:
        status = 200
        headers: dict[str, str] = {}
        content_length = 2
        content = object()

        async def __aenter__(self) -> "_Response":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _Session:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def get(self, _path: str, *, allow_redirects: bool) -> _Response:
            return _Response()

    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession",
        _Session,
    )
    with pytest.raises(WorkflowRegistryAuditError, match="response stream is invalid"):
        GitHubReadClient().get_json(f"/repos/{_REPOSITORY}/actions/workflows")


def test_memoryview_and_invalid_chunks_are_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact byte chunks are accepted; non-buffer chunks fail closed."""

    class _Content:
        def __init__(self, chunks: list[object]) -> None:
            self._chunks = chunks

        async def iter_chunked(self, _size: int):
            for chunk in self._chunks:
                yield chunk

    class _Response:
        status = 200
        headers: dict[str, str] = {}
        content_length = None

        def __init__(self, chunks: list[object]) -> None:
            self.content = _Content(chunks)

        async def __aenter__(self) -> "_Response":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _Session:
        chunks: list[object] = []

        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def get(self, _path: str, *, allow_redirects: bool) -> _Response:
            return _Response(_Session.chunks)

    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession",
        _Session,
    )
    _Session.chunks = [memoryview(b'{"ok":true}')]
    assert GitHubReadClient().get_json(f"/repos/{_REPOSITORY}/actions/workflows") == {
        "ok": True
    }

    _Session.chunks = ["not-bytes"]
    with pytest.raises(WorkflowRegistryAuditError, match="response stream is invalid"):
        GitHubReadClient().get_json(f"/repos/{_REPOSITORY}/actions/workflows")


def test_unauthenticated_client_omits_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkout-local dry runs must not invent a bearer token."""
    seen: dict[str, object] = {}

    class _Content:
        async def iter_chunked(self, _size: int):
            yield b"{}"

    class _Response:
        status = 200
        headers: dict[str, str] = {}
        content_length = 2
        content = _Content()

        async def __aenter__(self) -> "_Response":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _Session:
        def __init__(self, *, headers: dict[str, str], **_kwargs: object) -> None:
            seen["headers"] = headers

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def get(self, _path: str, *, allow_redirects: bool) -> _Response:
            return _Response()

    monkeypatch.setattr(
        "pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession",
        _Session,
    )
    GitHubReadClient().get_json(f"/repos/{_REPOSITORY}/actions/workflows")
    assert "Authorization" not in seen["headers"]


def test_live_ref_rejects_non_object_and_non_commit_payloads() -> None:
    """Protected-ref evidence must be an exact commit object."""
    with pytest.raises(WorkflowRegistryAuditError, match="protected ref response is invalid"):
        audit_live_protected_ref_workflows(
            repository_full_name=_REPOSITORY,
            protected_ref="main",
            expected_protected_sha=_PROTECTED_SHA,
            client=_StaticClient(
                {f"/repos/{_REPOSITORY}/git/ref/heads/main": ["not-an-object"]}
            ),
            captured_at="2026-08-16T00:00:00Z",
        )

    with pytest.raises(WorkflowRegistryAuditError, match="protected ref response is invalid"):
        audit_live_protected_ref_workflows(
            repository_full_name=_REPOSITORY,
            protected_ref="main",
            expected_protected_sha=_PROTECTED_SHA,
            client=_StaticClient(
                {
                    f"/repos/{_REPOSITORY}/git/ref/heads/main": {
                        "ref": "refs/heads/main",
                        "object": "commit",
                    }
                }
            ),
            captured_at="2026-08-16T00:00:00Z",
        )

    with pytest.raises(WorkflowRegistryAuditError, match="protected ref response is invalid"):
        audit_live_protected_ref_workflows(
            repository_full_name=_REPOSITORY,
            protected_ref="main",
            expected_protected_sha=_PROTECTED_SHA,
            client=_StaticClient(
                {
                    f"/repos/{_REPOSITORY}/git/ref/heads/main": {
                        "ref": "refs/heads/main",
                        "object": {"sha": _PROTECTED_SHA, "type": "tag"},
                    }
                }
            ),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_live_ref_lowercases_an_exact_commit_sha() -> None:
    """GitHub may return mixed-case hex; the receipt stays lowercase."""
    responses = _commit_and_tree()
    responses[f"/repos/{_REPOSITORY}/git/ref/heads/main"] = {
        "ref": "refs/heads/main",
        "object": {"sha": _PROTECTED_SHA.upper(), "type": "commit"},
    }
    receipt = audit_live_protected_ref_workflows(
        repository_full_name=_REPOSITORY,
        protected_ref="main",
        expected_protected_sha=_PROTECTED_SHA,
        client=_StaticClient(responses),
        captured_at="2026-08-16T00:00:00Z",
    )
    assert receipt["protected_sha"] == _PROTECTED_SHA
    assert receipt["protected_ref"] == "main"


def test_commit_tree_and_tree_container_shapes_fail_closed() -> None:
    """Malformed commit/tree containers cannot become a false empty path set."""
    responses = _commit_and_tree()
    responses[f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}"] = {
        "sha": _PROTECTED_SHA,
        "tree": "not-an-object",
    }
    with pytest.raises(WorkflowRegistryAuditError, match="commit response is invalid"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )

    responses = _commit_and_tree()
    responses[f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}"] = {
        "sha": _PROTECTED_SHA,
        "tree": {"sha": "not-a-sha"},
    }
    with pytest.raises(WorkflowRegistryAuditError, match="commit response is invalid"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )

    responses = _commit_and_tree()
    responses[f"/repos/{_REPOSITORY}/git/trees/{_TREE_SHA}?recursive=1"] = ["not-a-tree"]
    with pytest.raises(WorkflowRegistryAuditError, match="tree SHA does not match"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )

    responses = _commit_and_tree()
    responses[f"/repos/{_REPOSITORY}/git/trees/{_TREE_SHA}?recursive=1"] = {
        "sha": _TREE_SHA,
        "truncated": False,
        "tree": {"path": ".github/workflows/ci.yml"},
    }
    with pytest.raises(WorkflowRegistryAuditError, match="tree response is invalid"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_tree_entries_must_be_exact_blob_records() -> None:
    """Non-dict, non-string, and non-workflow entries stay fail-closed or ignored."""
    with pytest.raises(WorkflowRegistryAuditError, match="tree response is invalid"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(_commit_and_tree(tree_entries=["not-a-dict"])),
            captured_at="2026-08-16T00:00:00Z",
        )

    with pytest.raises(WorkflowRegistryAuditError, match="tree response is invalid"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(
                _commit_and_tree(tree_entries=[{"path": 1, "type": "blob"}])
            ),
            captured_at="2026-08-16T00:00:00Z",
        )

    receipt = audit_repository_workflows(
        repository_full_name=_REPOSITORY,
        protected_sha=_PROTECTED_SHA,
        client=_StaticClient(
            _commit_and_tree(
                tree_entries=[
                    {"path": "README.md", "type": "blob"},
                    {"path": ".github/workflows", "type": "tree"},
                ]
            )
        ),
        captured_at="2026-08-16T00:00:00Z",
    )
    assert receipt["protected_workflow_paths"] == []


def test_registry_container_and_overflow_fail_closed() -> None:
    """Registry pages must be objects whose row count cannot exceed total_count."""
    responses = _commit_and_tree()
    responses[f"/repos/{_REPOSITORY}/actions/workflows?per_page=100&page=1"] = [
        "not-an-object"
    ]
    with pytest.raises(WorkflowRegistryAuditError, match="registry response is invalid"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )

    with pytest.raises(WorkflowRegistryAuditError, match="changed during audit"):
        _read_registry(
            repository_full_name=_REPOSITORY,
            client=_StaticClient(
                {
                    f"/repos/{_REPOSITORY}/actions/workflows?per_page=100&page=1": {
                        "total_count": 1,
                        "workflows": [
                            {
                                "id": 1,
                                "path": ".github/workflows/ci.yml",
                                "state": "active",
                            },
                            {
                                "id": 2,
                                "path": ".github/workflows/release.yml",
                                "state": "active",
                            },
                        ],
                    }
                }
            ),
        )


def test_non_workflow_path_is_rejected_before_classification() -> None:
    """Only repository workflow blobs and dynamic/ identities are valid paths."""
    with pytest.raises(WorkflowRegistryAuditError, match="path is invalid"):
        _validate_workflow_record(
            {
                "id": 1,
                "path": "scripts/ci.yml",
                "state": "active",
            }
        )
