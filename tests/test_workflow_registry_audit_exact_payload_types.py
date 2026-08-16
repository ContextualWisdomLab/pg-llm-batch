"""Regression tests for exact primitive workflow-audit trust boundaries."""

from __future__ import annotations

import pytest

from workflow_registry_audit import (
    WorkflowRegistryAuditError,
    audit_live_protected_ref_workflows,
    audit_repository_workflows,
)


_PROTECTED_SHA = "a" * 40
_TREE_SHA = "b" * 40
_REPOSITORY = "ContextualWisdomLab/pg-llm-batch"


class _NoReadClient:
    def get_json(self, _path: str) -> dict[str, object]:
        raise AssertionError("invalid authority must fail before GitHub reads")


class _StaticClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses

    def get_json(self, path: str) -> dict[str, object]:
        return self._responses[path]  # type: ignore[return-value]


def _valid_responses() -> dict[str, object]:
    return {
        f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}": {
            "sha": _PROTECTED_SHA,
            "tree": {"sha": _TREE_SHA},
        },
        f"/repos/{_REPOSITORY}/git/trees/{_TREE_SHA}?recursive=1": {
            "sha": _TREE_SHA,
            "truncated": False,
            "tree": [],
        },
        f"/repos/{_REPOSITORY}/actions/workflows?per_page=100&page=1": {
            "total_count": 0,
            "workflows": [],
        },
    }


class _HostileRepository(str):
    def split(self, *_args, **_kwargs):
        raise AssertionError("hostile repository split executed")


class _HostileProtectedSha(str):
    def lower(self):
        raise AssertionError("hostile SHA lower executed")


class _HostileProtectedRef(str):
    def startswith(self, *_args, **_kwargs):
        raise AssertionError("hostile ref startswith executed")


class _HostileMapping(dict):
    def get(self, *_args, **_kwargs):
        raise AssertionError("hostile mapping get executed")


class _HostileInt(int):
    def __lt__(self, _other):
        raise AssertionError("hostile integer comparison executed")


class _HostileList(list):
    def __len__(self):
        raise AssertionError("hostile list length executed")


@pytest.mark.parametrize(
    ("repository_full_name", "protected_sha"),
    [
        (_HostileRepository(_REPOSITORY), _PROTECTED_SHA),
        (_REPOSITORY, _HostileProtectedSha(_PROTECTED_SHA)),
    ],
)
def test_audit_rejects_hostile_authority_subclasses_before_client_access(
    repository_full_name, protected_sha
):
    with pytest.raises(WorkflowRegistryAuditError):
        audit_repository_workflows(
            repository_full_name=repository_full_name,
            protected_sha=protected_sha,
            client=_NoReadClient(),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_live_audit_rejects_hostile_ref_subclass_before_client_access():
    with pytest.raises(WorkflowRegistryAuditError):
        audit_live_protected_ref_workflows(
            repository_full_name=_REPOSITORY,
            protected_ref=_HostileProtectedRef("main"),
            expected_protected_sha=_PROTECTED_SHA,
            client=_NoReadClient(),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_audit_rejects_hostile_top_level_commit_mapping_without_member_access():
    responses = _valid_responses()
    responses[f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}"] = _HostileMapping()
    with pytest.raises(WorkflowRegistryAuditError):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_audit_rejects_hostile_nested_commit_tree_without_member_access():
    responses = _valid_responses()
    responses[f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}"] = {
        "sha": _PROTECTED_SHA,
        "tree": _HostileMapping(),
    }
    with pytest.raises(WorkflowRegistryAuditError):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_audit_rejects_hostile_registry_total_count_before_comparison():
    responses = _valid_responses()
    responses[f"/repos/{_REPOSITORY}/actions/workflows?per_page=100&page=1"] = {
        "total_count": _HostileInt(0),
        "workflows": [],
    }
    with pytest.raises(WorkflowRegistryAuditError):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_audit_rejects_hostile_registry_list_before_shape_operations():
    responses = _valid_responses()
    responses[f"/repos/{_REPOSITORY}/actions/workflows?per_page=100&page=1"] = {
        "total_count": 0,
        "workflows": _HostileList(),
    }
    with pytest.raises(WorkflowRegistryAuditError):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )
