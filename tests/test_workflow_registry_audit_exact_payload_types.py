"""Regression tests for exact primitive workflow-audit trust boundaries."""

from __future__ import annotations

import pytest

from pg_llm_batch.workflow_registry_audit import (
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


_SECRET_IDENTITY = "SECRET-SENTINEL hostile identity member"


class _LyingIdentity(str):
    def __eq__(self, _other: object) -> bool:
        return True

    def __ne__(self, _other: object) -> bool:
        return False


class _RaisingIdentity(str):
    def __eq__(self, _other: object) -> bool:
        raise RuntimeError(_SECRET_IDENTITY)

    def __ne__(self, _other: object) -> bool:
        raise RuntimeError(_SECRET_IDENTITY)


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


def test_audit_rejects_lying_commit_sha_before_tree_resolution() -> None:
    """A sha subclass must not certify the caller SHA while resolving another tree."""
    planted_tree = "c" * 40
    planted_path = ".github/workflows/planted.yml"
    responses = _valid_responses()
    responses[f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}"] = {
        "sha": _LyingIdentity(planted_tree),
        "tree": {"sha": planted_tree},
    }
    responses[f"/repos/{_REPOSITORY}/git/trees/{planted_tree}?recursive=1"] = {
        "sha": planted_tree,
        "truncated": False,
        "tree": [{"path": planted_path, "type": "blob"}],
    }

    with pytest.raises(WorkflowRegistryAuditError, match="commit response is invalid"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_audit_rejects_raising_commit_sha_without_leaking_custom_code() -> None:
    """Identity comparison must not execute subclass equality methods."""
    responses = _valid_responses()
    responses[f"/repos/{_REPOSITORY}/git/commits/{_PROTECTED_SHA}"] = {
        "sha": _RaisingIdentity(_PROTECTED_SHA),
        "tree": {"sha": _TREE_SHA},
    }

    with pytest.raises(WorkflowRegistryAuditError, match="commit response is invalid") as caught:
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )

    assert _SECRET_IDENTITY not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_audit_rejects_lying_tree_sha_before_path_collection() -> None:
    """Tree object identity must be an exact decoder string before comparison."""
    planted_tree = "c" * 40
    responses = _valid_responses()
    responses[f"/repos/{_REPOSITORY}/git/trees/{_TREE_SHA}?recursive=1"] = {
        "sha": _LyingIdentity(planted_tree),
        "truncated": False,
        "tree": [{"path": ".github/workflows/planted.yml", "type": "blob"}],
    }

    with pytest.raises(WorkflowRegistryAuditError, match="tree SHA does not match"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_StaticClient(responses),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_live_audit_rejects_lying_ref_member_before_equality() -> None:
    """A ref subclass must not certify the requested branch by lying about equality."""

    class _LyingRefClient:
        def get_json(self, path: str) -> dict[str, object]:
            if path == f"/repos/{_REPOSITORY}/git/ref/heads/main":
                return {
                    "ref": _LyingIdentity("refs/heads/other"),
                    "object": {"sha": _PROTECTED_SHA, "type": "commit"},
                }
            raise AssertionError(f"unexpected GitHub read: {path}")

    with pytest.raises(WorkflowRegistryAuditError, match="protected ref response is invalid"):
        audit_live_protected_ref_workflows(
            repository_full_name=_REPOSITORY,
            protected_ref="main",
            expected_protected_sha=_PROTECTED_SHA,
            client=_LyingRefClient(),
            captured_at="2026-08-16T00:00:00Z",
        )


def test_live_audit_rejects_raising_ref_member_without_leaking_custom_code() -> None:
    """Protected-ref membership checks must not run subclass equality methods."""

    class _RaisingRefClient:
        def get_json(self, path: str) -> dict[str, object]:
            if path == f"/repos/{_REPOSITORY}/git/ref/heads/main":
                return {
                    "ref": _RaisingIdentity("refs/heads/main"),
                    "object": {"sha": _PROTECTED_SHA, "type": "commit"},
                }
            raise AssertionError(f"unexpected GitHub read: {path}")

    with pytest.raises(WorkflowRegistryAuditError, match="protected ref response is invalid") as caught:
        audit_live_protected_ref_workflows(
            repository_full_name=_REPOSITORY,
            protected_ref="main",
            expected_protected_sha=_PROTECTED_SHA,
            client=_RaisingRefClient(),
            captured_at="2026-08-16T00:00:00Z",
        )

    assert _SECRET_IDENTITY not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_audit_generates_rfc3339_captured_at_when_omitted() -> None:
    """Operators receive a UTC receipt timestamp when they do not supply one."""
    receipt = audit_repository_workflows(
        repository_full_name=_REPOSITORY,
        protected_sha=_PROTECTED_SHA,
        client=_StaticClient(_valid_responses()),
    )
    assert type(receipt["captured_at"]) is str
    assert receipt["captured_at"].endswith("Z")


def test_audit_rejects_non_string_captured_at_before_receipt() -> None:
    """Receipt timestamps must be exact strings or omitted."""
    with pytest.raises(WorkflowRegistryAuditError, match="captured_at"):
        audit_repository_workflows(
            repository_full_name=_REPOSITORY,
            protected_sha=_PROTECTED_SHA,
            client=_NoReadClient(),
            captured_at=20260816,  # type: ignore[arg-type]
        )
