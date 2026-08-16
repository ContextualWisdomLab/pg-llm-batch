# SPDX-License-Identifier: Apache-2.0
"""Integrity regressions for packaged PostgreSQL schema evidence."""

from __future__ import annotations

import hashlib
from importlib import resources
from io import BytesIO

import pytest

import pg_llm_batch.postgres_schema_evidence as schema_evidence
from pg_llm_batch.postgres_schema_evidence import (
    PostgresSchemaEvidenceError,
    inspect_postgres_schema,
)


class _ReadFailure(BytesIO):
    """Expose one deterministic lower-layer read failure for error-boundary tests."""

    def read(self, size: int = -1) -> bytes:
        del size
        raise OSError("sensitive schema read diagnostic")


class _CloseFailure(BytesIO):
    """Expose one deterministic lower-layer close failure for cleanup tests."""

    def close(self) -> None:
        raise OSError("sensitive schema close diagnostic")


class _ReadAndCloseFailure(_ReadFailure):
    """Fail both reading and cleanup so the primary bounded error can be asserted."""

    def close(self) -> None:
        raise OSError("sensitive schema close diagnostic")


def test_inspector_matches_packaged_schema_identity() -> None:
    """Bind evidence exactly to the bytes distributed as the package schema."""
    payload = resources.files("pg_llm_batch").joinpath("schema.sql").read_bytes()

    evidence = inspect_postgres_schema()

    assert evidence.sha256 == hashlib.sha256(payload).hexdigest()
    assert evidence.size_bytes == len(payload)
    assert evidence.as_dict() == {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }
    assert payload.decode("utf-8") not in repr(evidence)


def test_inspector_normalizes_resource_open_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not expose import-resource diagnostics when the packaged schema is missing."""

    def failing_files(package: str) -> object:
        del package
        raise OSError("sensitive package resource diagnostic")

    monkeypatch.setattr(schema_evidence.resources, "files", failing_files)

    with pytest.raises(PostgresSchemaEvidenceError) as raised:
        inspect_postgres_schema()

    assert str(raised.value) == "PostgreSQL package schema could not be opened"
    assert "sensitive package resource diagnostic" not in str(raised.value)


def test_inspector_rejects_empty_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed instead of issuing an identity for an empty package schema."""
    monkeypatch.setattr(schema_evidence, "_open_schema_resource", lambda: BytesIO())

    with pytest.raises(PostgresSchemaEvidenceError, match="positive bounded size"):
        inspect_postgres_schema()


def test_inspector_rejects_oversized_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound hashing work even if package-resource integrity has been compromised."""
    monkeypatch.setattr(schema_evidence, "_MAX_SCHEMA_BYTES", 4)
    monkeypatch.setattr(
        schema_evidence,
        "_open_schema_resource",
        lambda: BytesIO(b"12345"),
    )

    with pytest.raises(PostgresSchemaEvidenceError, match="positive bounded size"):
        inspect_postgres_schema()


def test_inspector_normalizes_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep lower-layer read diagnostics outside the recovery evidence contract."""
    monkeypatch.setattr(
        schema_evidence,
        "_open_schema_resource",
        lambda: _ReadFailure(b"schema"),
    )

    with pytest.raises(PostgresSchemaEvidenceError) as raised:
        inspect_postgres_schema()

    assert str(raised.value) == "PostgreSQL package schema could not be read"
    assert "sensitive schema read diagnostic" not in str(raised.value)


def test_inspector_normalizes_success_path_close_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose a fixed content-free error when successful inspection cannot clean up."""
    monkeypatch.setattr(
        schema_evidence,
        "_open_schema_resource",
        lambda: _CloseFailure(b"schema"),
    )

    with pytest.raises(PostgresSchemaEvidenceError) as raised:
        inspect_postgres_schema()

    assert str(raised.value) == "PostgreSQL package schema stream could not be closed"
    assert "sensitive schema close diagnostic" not in str(raised.value)


def test_close_failure_does_not_mask_primary_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the primary bounded read error when best-effort cleanup also fails."""
    monkeypatch.setattr(
        schema_evidence,
        "_open_schema_resource",
        lambda: _ReadAndCloseFailure(b"schema"),
    )

    with pytest.raises(PostgresSchemaEvidenceError) as raised:
        inspect_postgres_schema()

    assert str(raised.value) == "PostgreSQL package schema could not be read"
    assert "sensitive schema close diagnostic" not in str(raised.value)
