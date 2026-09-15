# SPDX-License-Identifier: Apache-2.0
"""Adversarial authority-boundary tests for durable checkpoint persistence."""

from __future__ import annotations

import pytest

import pg_llm_batch.checkpoint_store as checkpoint_store
from pg_llm_batch.exceptions import ConfigError, ValidationError
from pg_llm_batch.result_streaming import BatchResultCheckpoint


class _HostileDsn(str):
    """Expose behavior if a caller-controlled string subtype is trusted."""

    def strip(self, *_args: object, **_kwargs: object) -> str:
        """Fail if validation invokes caller-controlled string behavior."""
        raise AssertionError("caller-controlled DSN behavior executed")


class _HostileCheckpoint(BatchResultCheckpoint):
    """Expose behavior if checkpoint subtype fields are read before rejection."""

    def __getattribute__(self, name: str) -> object:
        """Fail if persistence reads behavior-bearing checkpoint fields."""
        if name in {
            "file_line_number",
            "batch_line_count",
            "record_count",
        }:
            raise AssertionError("caller-controlled checkpoint behavior executed")
        return super().__getattribute__(name)


class _HostileText(str):
    """Expose behavior if a mutated checkpoint string subtype is trusted."""

    def strip(self, *_args: object, **_kwargs: object) -> str:
        """Fail if persistence invokes caller-controlled string behavior."""
        raise AssertionError("caller-controlled checkpoint text behavior executed")

    def __eq__(self, _other: object) -> bool:
        """Fail if persistence compares caller-controlled string behavior."""
        raise AssertionError("caller-controlled checkpoint text behavior executed")


class _HostileInteger(int):
    """Expose behavior if a mutated checkpoint integer subtype is trusted."""

    def __gt__(self, _other: object) -> bool:
        """Fail if persistence compares caller-controlled integer behavior."""
        raise AssertionError("caller-controlled checkpoint integer behavior executed")

    def __le__(self, _other: object) -> bool:
        """Fail if persistence compares caller-controlled integer behavior."""
        raise AssertionError("caller-controlled checkpoint integer behavior executed")


class _HostilePersistenceKey(str):
    """Expose behavior if a persistence-key string subtype is trusted."""

    def strip(self, *_args: object, **_kwargs: object) -> str:
        """Fail if persistence invokes caller-controlled normalization behavior."""
        raise AssertionError("caller-controlled persistence-key behavior executed")

    def __eq__(self, _other: object) -> bool:
        """Fail if persistence compares caller-controlled key behavior."""
        raise AssertionError("caller-controlled persistence-key behavior executed")


def _checkpoint() -> BatchResultCheckpoint:
    """Build one ordinary package checkpoint for authority-boundary tests."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-1",
        endpoint_alias="default",
        file_kind="result",
        file_id="file-1",
        file_line_number=2,
        batch_line_count=2,
        record_count=1,
        prefix_sha256="a" * 64,
    )


def _hostile_checkpoint() -> _HostileCheckpoint:
    """Build a hostile subtype without running its inherited validation hooks."""
    ordinary = _checkpoint()
    candidate = object.__new__(_HostileCheckpoint)
    for field_name, field_value in vars(ordinary).items():
        object.__setattr__(candidate, field_name, field_value)
    return candidate


def test_dsn_subclass_is_rejected_without_executing_caller_behavior() -> None:
    """Database-target validation must not invoke a caller-controlled str subtype."""
    with pytest.raises(ConfigError, match="Postgres DSN"):
        checkpoint_store._validated_postgres_dsn(_HostileDsn("postgresql://secret"))


def test_checkpoint_subclass_is_rejected_before_field_access() -> None:
    """Checkpoint persistence must reject behavior-bearing subtypes before reads."""
    candidate = _hostile_checkpoint()

    with pytest.raises(ValidationError, match="BatchResultCheckpoint"):
        checkpoint_store._validated_checkpoint(candidate, "checkpoint")


def test_mutated_checkpoint_string_subclass_is_rejected_before_behavior() -> None:
    """Persistence must reject a behavior-bearing string field before validation."""
    candidate = _checkpoint()
    object.__setattr__(candidate, "batch_id", _HostileText("batch-1"))

    with pytest.raises(ValidationError, match="exact built-in primitive") as raised:
        checkpoint_store._validated_checkpoint(candidate, "checkpoint")

    assert raised.value.details["field"] == "checkpoint.batch_id"
    assert raised.value.details["value"] == "<redacted>"


def test_mutated_checkpoint_integer_subclass_is_rejected_before_behavior() -> None:
    """Persistence must reject a behavior-bearing integer field before comparison."""
    candidate = _checkpoint()
    object.__setattr__(candidate, "record_count", _HostileInteger(1))

    with pytest.raises(ValidationError, match="exact built-in primitive") as raised:
        checkpoint_store._validated_checkpoint(candidate, "checkpoint")

    assert raised.value.details["field"] == "checkpoint.record_count"
    assert raised.value.details["value"] == "<redacted>"


def test_validated_checkpoint_is_a_package_owned_snapshot() -> None:
    """Validation must detach persistence authority from the caller-owned object."""
    candidate = _checkpoint()

    validated = checkpoint_store._validated_checkpoint(candidate, "checkpoint")

    assert validated == candidate
    assert validated is not candidate
    assert type(validated) is BatchResultCheckpoint


def test_consumer_name_subclass_is_rejected_before_persistence() -> None:
    """Checkpoint consumer identity must not retain caller string-subtype authority."""
    candidate = _HostilePersistenceKey("consumer-1")

    with pytest.raises(ValidationError) as raised:
        checkpoint_store.validate_checkpoint_consumer_name(candidate)

    assert raised.value.details["field"] == "consumer_name"
    assert raised.value.details["value"] == "<redacted>"


def test_batch_id_subclass_is_rejected_before_persistence() -> None:
    """Remote batch identity must not retain caller string-subtype authority."""
    candidate = _HostilePersistenceKey("batch-1")

    with pytest.raises(ValidationError) as raised:
        checkpoint_store._validated_batch_id(candidate)

    assert raised.value.details["field"] == "batch_id"
    assert raised.value.details["value"] == "<redacted>"


def test_endpoint_alias_subclass_is_rejected_before_normalization() -> None:
    """Endpoint identity must reject a subtype before caller-controlled strip()."""
    candidate = _HostilePersistenceKey("default")

    with pytest.raises(ValidationError) as raised:
        checkpoint_store._validated_exact_endpoint_alias(candidate)

    assert raised.value.details["field"] == "endpoint_alias"
    assert raised.value.details["value"] == "<redacted>"


def test_tenant_scope_subclass_is_rejected_during_store_construction() -> None:
    """Tenant authority must be exact package-owned text before store retention."""
    candidate = _HostilePersistenceKey("tenant-1")

    with pytest.raises(ValidationError) as raised:
        checkpoint_store.PostgresBatchResultCheckpointStore(
            "postgresql://localhost/postgres",
            tenant_scope=candidate,
        )

    assert raised.value.details["field"] == "tenant_scope"
    assert raised.value.details["value"] == "<redacted>"
