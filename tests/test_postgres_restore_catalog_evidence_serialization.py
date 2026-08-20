# SPDX-License-Identifier: Apache-2.0
"""Serialization-integrity regressions for restore-catalog evidence."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.postgres_restore_acceptance as restore_acceptance
from pg_llm_batch.postgres_restore_acceptance import (
    PostgresRestoreAcceptanceError,
    PostgresRestoreCatalogEvidence,
)
from pg_llm_batch.postgres_schema_evidence import inspect_postgres_schema


def _evidence() -> PostgresRestoreCatalogEvidence:
    """Build one semantically valid catalog-evidence object from package identity."""
    schema = inspect_postgres_schema()
    return PostgresRestoreCatalogEvidence(
        required_table_count=len(restore_acceptance._REQUIRED_TABLES),
        required_index_count=len(restore_acceptance._REQUIRED_INDEXES),
        lifecycle_rls_enabled=True,
        lifecycle_rls_forced=True,
        checkpoint_store_present=True,
        checkpoint_store_rls_forced=True,
        expected_schema_sha256=schema.sha256,
        expected_schema_size_bytes=schema.size_bytes,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_table_count", 0),
        ("required_index_count", 0),
        ("lifecycle_rls_enabled", False),
        ("lifecycle_rls_forced", False),
        ("checkpoint_store_present", False),
        ("checkpoint_store_rls_forced", False),
        ("expected_schema_sha256", "A" * 64),
        ("expected_schema_size_bytes", 0),
        ("required_table_count", True),
        ("checkpoint_store_present", 1),
        ("expected_schema_size_bytes", True),
    ],
)
def test_as_dict_rejects_post_construction_mutation(
    field: str,
    value: object,
) -> None:
    """Serialization must reject mutated fields instead of reflecting them."""
    evidence = _evidence()
    object.__setattr__(evidence, field, value)

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog evidence is invalid",
    ) as caught:
        evidence.as_dict()

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_as_dict_rejects_deleted_slot_with_bounded_error() -> None:
    """A deleted frozen-dataclass slot must not leak raw AttributeError."""
    evidence = _evidence()
    object.__delattr__(evidence, "expected_schema_sha256")

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog evidence is invalid",
    ) as caught:
        evidence.as_dict()

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_as_dict_rejects_validly_shaped_but_wrong_schema_identity() -> None:
    """Syntactically valid digest evidence must still match the packaged schema."""
    evidence = _evidence()
    replacement = "0" * 64
    if evidence.expected_schema_sha256 == replacement:
        replacement = "1" * 64
    object.__setattr__(evidence, "expected_schema_sha256", replacement)

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog evidence is invalid",
    ) as caught:
        evidence.as_dict()

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_as_dict_hides_package_schema_revalidation_failure(monkeypatch: Any) -> None:
    """Package-resource failures must not become serialized recovery diagnostics."""
    evidence = _evidence()

    def fail_inspection() -> Any:
        raise RuntimeError("SECRET-SENTINEL package loader diagnostic")

    monkeypatch.setattr(
        restore_acceptance,
        "inspect_postgres_schema",
        fail_inspection,
    )

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog evidence is invalid",
    ) as caught:
        evidence.as_dict()

    assert "SECRET-SENTINEL" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_as_dict_uses_one_snapshot_before_package_schema_revalidation(
    monkeypatch: Any,
) -> None:
    """A later mutation cannot replace authority after serialization snapshots it."""
    evidence = _evidence()
    original_inspect = restore_acceptance.inspect_postgres_schema

    def mutate_then_inspect() -> Any:
        object.__setattr__(evidence, "required_table_count", 0)
        return original_inspect()

    monkeypatch.setattr(
        restore_acceptance,
        "inspect_postgres_schema",
        mutate_then_inspect,
    )

    serialized = evidence.as_dict()

    assert evidence.required_table_count == 0
    assert serialized["required_table_count"] == len(
        restore_acceptance._REQUIRED_TABLES
    )
