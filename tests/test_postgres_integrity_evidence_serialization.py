# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bounded PostgreSQL evidence serialization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
    PostgresBackupEvidenceError,
)
from pg_llm_batch.postgres_schema_evidence import (
    PostgresSchemaEvidence,
    PostgresSchemaEvidenceError,
)


_VALID_SHA256 = "a" * 64
_MAX_SCHEMA_BYTES = 16 * 1024 * 1024
_MAX_SIGNED_BIGINT = (1 << 63) - 1


def _backup_evidence() -> PostgresBackupArtifactEvidence:
    return PostgresBackupArtifactEvidence(sha256=_VALID_SHA256, size_bytes=4096)


def _schema_evidence() -> PostgresSchemaEvidence:
    return PostgresSchemaEvidence(sha256=_VALID_SHA256, size_bytes=4096)


@pytest.mark.parametrize(
    ("factory", "error_type"),
    [
        (_backup_evidence, PostgresBackupEvidenceError),
        (_schema_evidence, PostgresSchemaEvidenceError),
    ],
)
def test_evidence_serialization_rejects_mutated_unbounded_digest_without_reflection(
    factory: Callable[[], Any],
    error_type: type[ValueError],
) -> None:
    evidence = factory()
    secret_detail = "deployment-secret/" + "x" * 4096
    object.__setattr__(evidence, "sha256", secret_detail)

    with pytest.raises(error_type) as raised:
        evidence.as_dict()

    assert secret_detail not in str(raised.value)


@pytest.mark.parametrize(
    ("factory", "error_type"),
    [
        (_backup_evidence, PostgresBackupEvidenceError),
        (_schema_evidence, PostgresSchemaEvidenceError),
    ],
)
def test_evidence_serialization_normalizes_deleted_required_field(
    factory: Callable[[], Any],
    error_type: type[ValueError],
) -> None:
    evidence = factory()
    object.__delattr__(evidence, "size_bytes")

    with pytest.raises(error_type):
        evidence.as_dict()


@pytest.mark.parametrize("size_bytes", [False, 0, _MAX_SIGNED_BIGINT + 1])
def test_backup_evidence_serialization_rejects_invalid_mutated_size(
    size_bytes: object,
) -> None:
    evidence = _backup_evidence()
    object.__setattr__(evidence, "size_bytes", size_bytes)

    with pytest.raises(PostgresBackupEvidenceError):
        evidence.as_dict()


@pytest.mark.parametrize("size_bytes", [False, 0, _MAX_SCHEMA_BYTES + 1])
def test_schema_evidence_serialization_rejects_invalid_mutated_size(
    size_bytes: object,
) -> None:
    evidence = _schema_evidence()
    object.__setattr__(evidence, "size_bytes", size_bytes)

    with pytest.raises(PostgresSchemaEvidenceError):
        evidence.as_dict()


def test_valid_manual_evidence_serialization_remains_schema_only() -> None:
    assert _backup_evidence().as_dict() == {
        "sha256": _VALID_SHA256,
        "size_bytes": 4096,
    }
    assert _schema_evidence().as_dict() == {
        "sha256": _VALID_SHA256,
        "size_bytes": 4096,
    }
