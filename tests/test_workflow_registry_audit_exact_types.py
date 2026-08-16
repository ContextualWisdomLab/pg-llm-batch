"""Hostile primitive-subclass regressions for workflow registry evidence."""

from __future__ import annotations

from typing import Any

import pytest

from workflow_registry_audit import (
    WorkflowRegistryAuditError,
    _validate_workflow_record,
)

_SECRET_SENTINEL = "SECRET-SENTINEL hostile registry primitive"


class _HostileWorkflowRecord(dict[str, object]):
    """Execute caller-controlled code when record members are retrieved."""

    def get(self, _key: str, _default: object = None) -> object:
        """Raise instead of supplying trustworthy decoded JSON members."""
        raise RuntimeError(_SECRET_SENTINEL)


class _HostileWorkflowId(int):
    """Execute caller-controlled code when numeric range validation runs."""

    def __gt__(self, _other: object) -> bool:
        """Raise instead of supplying a trustworthy positive-ID comparison."""
        raise RuntimeError(_SECRET_SENTINEL)


class _HostileWorkflowPath(str):
    """Execute caller-controlled code when path components are inspected."""

    def split(self, *_args: object, **_kwargs: object) -> list[str]:
        """Raise instead of supplying trustworthy path components."""
        raise RuntimeError(_SECRET_SENTINEL)


class _HostileWorkflowState(str):
    """Execute caller-controlled code during finite-state membership checks."""

    def __hash__(self) -> int:
        """Raise instead of supplying a trustworthy state hash."""
        raise RuntimeError(_SECRET_SENTINEL)


@pytest.mark.parametrize(
    "state",
    [[], {}, {"active"}],
)
def test_unhashable_workflow_state_is_bounded_invalid_evidence(state: Any) -> None:
    """Malformed state containers must not escape as raw ``TypeError``."""
    with pytest.raises(WorkflowRegistryAuditError, match="record is invalid") as caught:
        _validate_workflow_record(
            {
                "id": 1,
                "path": ".github/workflows/ci.yml",
                "state": state,
            }
        )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_record_subclass_is_rejected_before_member_access() -> None:
    """Registry parsing must not execute caller-controlled mapping methods."""
    with pytest.raises(WorkflowRegistryAuditError, match="record is invalid") as caught:
        _validate_workflow_record(
            _HostileWorkflowRecord(
                id=1,
                path=".github/workflows/ci.yml",
                state="active",
            )
        )

    assert _SECRET_SENTINEL not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", _HostileWorkflowId(1)),
        ("path", _HostileWorkflowPath(".github/workflows/ci.yml")),
        ("state", _HostileWorkflowState("active")),
    ],
)
def test_primitive_subclasses_are_rejected_before_custom_code(
    field: str,
    value: object,
) -> None:
    """Registry evidence must use exact decoder primitive types only."""
    record: dict[str, object] = {
        "id": 1,
        "path": ".github/workflows/ci.yml",
        "state": "active",
    }
    record[field] = value

    with pytest.raises(WorkflowRegistryAuditError, match="record is invalid") as caught:
        _validate_workflow_record(record)

    assert _SECRET_SENTINEL not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
