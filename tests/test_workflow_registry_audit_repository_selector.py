"""Regression tests for bounded workflow-audit repository selectors."""

from __future__ import annotations

import pytest

from workflow_registry_audit import (
    WorkflowRegistryAuditError,
    audit_repository_workflows,
)


PROTECTED_SHA = "d0a4b30be1f46536e352443309f3a35533156767"


class _NoReadClient:
    """Reject every GitHub read so validation ordering is explicit."""

    def __init__(self) -> None:
        self.requested_paths: list[str] = []

    def get_json(self, path: str) -> dict[str, object]:
        """Record and reject transport that input validation should prevent."""
        self.requested_paths.append(path)
        raise AssertionError(f"unexpected GitHub read: {path}")


@pytest.mark.parametrize(
    "repository_full_name",
    [
        "../repo",
        "./repo",
        "owner/..",
        "owner/.",
    ],
)
def test_repository_dot_segments_fail_before_github_read(
    repository_full_name: str,
) -> None:
    """Dot segments must not escape the fixed ``/repos/owner/name`` API namespace."""
    client = _NoReadClient()

    with pytest.raises(WorkflowRegistryAuditError, match="owner/name syntax"):
        audit_repository_workflows(
            repository_full_name=repository_full_name,
            protected_sha=PROTECTED_SHA,
            client=client,
            captured_at="2026-08-15T00:00:00Z",
        )

    assert client.requested_paths == []
