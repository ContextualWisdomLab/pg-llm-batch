# SPDX-License-Identifier: Apache-2.0
"""Regression tests for bounded canonical workflow-audit timestamps."""

from __future__ import annotations

import pytest

from pg_llm_batch.workflow_registry_audit import (
    WorkflowRegistryAuditError,
    _utc_timestamp,
    _validate_captured_at,
    audit_live_protected_ref_workflows,
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
        "0000-01-01T00:00:00Z",
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


def test_live_ref_audit_rejects_invalid_captured_at_before_github_access() -> None:
    """Live-ref audits use the same bounded timestamp gate as SHA-only audits."""
    with pytest.raises(
        WorkflowRegistryAuditError,
        match="captured_at must be a canonical UTC RFC 3339 timestamp",
    ):
        audit_live_protected_ref_workflows(
            repository_full_name="ContextualWisdomLab/pg-llm-batch",
            protected_ref="main",
            expected_protected_sha="a" * 40,
            client=_NoReadClient(),
            captured_at="not-a-time",
        )


def test_generated_utc_timestamp_satisfies_captured_at_gate() -> None:
    """The auditor clock must emit the same canonical shape the gate accepts."""
    generated = _utc_timestamp()
    _validate_captured_at(generated)
    assert generated.endswith("Z")
