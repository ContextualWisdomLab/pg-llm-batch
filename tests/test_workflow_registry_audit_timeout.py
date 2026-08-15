"""Timeout-boundary regressions for the read-only workflow registry audit."""

from __future__ import annotations

import math

import pytest

from workflow_registry_audit import GitHubReadClient, WorkflowRegistryAuditError


@pytest.mark.parametrize("timeout_seconds", [math.nan, math.inf])
def test_nonfinite_timeout_is_rejected_before_transport(timeout_seconds: float) -> None:
    """NaN and infinity cannot disable the client's finite timeout contract."""
    with pytest.raises(WorkflowRegistryAuditError, match="positive finite"):
        GitHubReadClient(timeout_seconds=timeout_seconds)
