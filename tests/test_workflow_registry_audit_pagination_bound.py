"""Regression test for globally bounded workflow-registry pagination."""

from __future__ import annotations

import pytest

from workflow_registry_audit import WorkflowRegistryAuditError, _read_registry


class _OversizedRegistryClient:
    """Expose an implausibly large registry cardinality without real network work."""

    def __init__(self) -> None:
        self.calls = 0

    def get_json(self, _path: str) -> dict[str, object]:
        """Return one full page while claiming an excessive registry size."""
        self.calls += 1
        return {
            "total_count": 10_001,
            "workflows": [
                {
                    "id": workflow_id,
                    "path": f".github/workflows/workflow-{workflow_id}.yml",
                    "state": "active",
                }
                for workflow_id in range(1, 101)
            ],
        }


def test_excessive_registry_cardinality_fails_before_second_page() -> None:
    """One audit must cap total API work instead of trusting unbounded cardinality."""
    client = _OversizedRegistryClient()

    with pytest.raises(
        WorkflowRegistryAuditError,
        match="workflow registry exceeds supported workflow limit",
    ):
        _read_registry(
            repository_full_name="ContextualWisdomLab/pg-llm-batch",
            client=client,
        )

    assert client.calls == 1
