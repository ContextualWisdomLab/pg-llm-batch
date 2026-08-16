# SPDX-License-Identifier: Apache-2.0
"""Regression tests for bounded canonical workflow-audit timestamps."""

from __future__ import annotations

import pytest

from pg_llm_batch.workflow_registry_audit import (
    WorkflowRegistryAuditError,
    audit_repository_workflows,
)


class _NoReadClient:
    """Prove invalid receipt timestamps fail before any GitHub read."""

    def get_json(self, path: str) -> dict[str, object]:
        del path
        raise AssertionError("invalid captured_at must fail before GitHub access")


@pytest.mark.parametrize(
    "captured_at",
    [
        "",
        "not-a-time",
        "2026-08-16 16:20:00Z",
        "2026-08-16T16:20:00+00:00",
        "2026-08-16T16:20:00.000Z",
        "2026-8-16T16:20:00Z",
        "2026-02-30T16:20:00Z",
        "2026-08-16T24:00:00Z",
        "2026-08-16T16:20:00z",
        "2" * 10_000,
    ],
)
def test_invalid_captured_at_fails_before_github_access(captured_at: str) -> None:
    """Reject malformed, noncanonical, non-UTC, or unbounded receipt timestamps."""
    with pytest.raises(
        WorkflowRegistryAuditError,
        match="captured_at must be a canonical UTC RFC 3339 timestamp",
    ):
        audit_repository_workflows(
            repository_full_name="ContextualWisdomLab/pg-llm-batch",
            protected_sha="a" * 40,
            client=_NoReadClient(),
            captured_at=captured_at,
        )
