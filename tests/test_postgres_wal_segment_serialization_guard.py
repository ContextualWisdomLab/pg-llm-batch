# SPDX-License-Identifier: Apache-2.0
"""Regression guards for stable PostgreSQL WAL evidence serialization."""

from __future__ import annotations

from pathlib import Path

import pytest

import pg_llm_batch.postgres_wal_segment_evidence as wal_evidence
from pg_llm_batch.postgres_backup_evidence import inspect_postgres_backup_artifact
from pg_llm_batch.postgres_wal_segment_evidence import (
    PostgresWalSegmentEvidenceError,
    bind_postgres_wal_segment_evidence,
    postgres_wal_segment_binding_is_valid,
)

_MIB = 1024 * 1024
_SEGMENT_NAME = "000000010000000000000001"


def _binding(tmp_path: Path) -> wal_evidence.PostgresWalSegmentBinding:
    """Create one provenance-backed binding over realistic WAL-sized bytes."""
    artifact_path = tmp_path / "wal-segment"
    artifact_path.write_bytes(b"W" * _MIB)
    artifact = inspect_postgres_backup_artifact(
        str(artifact_path),
        maximum_size_bytes=_MIB,
    )
    return bind_postgres_wal_segment_evidence(
        segment_name=_SEGMENT_NAME,
        wal_segment_size_bytes=_MIB,
        artifact_evidence=artifact,
    )


def test_as_dict_rejects_binding_tampered_after_validation(tmp_path: Path) -> None:
    """Serialization must not emit authority fields from an invalidated binding."""
    binding = _binding(tmp_path)
    object.__setattr__(binding, "segment_name", "000000010000000000000000")

    with pytest.raises(PostgresWalSegmentEvidenceError):
        binding.as_dict()


def test_validator_rejects_authority_mutation_during_provenance_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provenance check cannot authorize fields changed while validation runs."""
    binding = _binding(tmp_path)
    artifact = binding.artifact_evidence
    original_check = wal_evidence.postgres_backup_artifact_evidence_was_inspected

    def mutate_after_inspection(evidence: object) -> bool:
        inspected = original_check(evidence)
        assert inspected is True
        object.__setattr__(binding, "sha256", "F" * 64)
        object.__setattr__(artifact, "sha256", "F" * 64)
        return True

    monkeypatch.setattr(
        wal_evidence,
        "postgres_backup_artifact_evidence_was_inspected",
        mutate_after_inspection,
    )

    assert postgres_wal_segment_binding_is_valid(binding) is False


def test_validator_rejects_nonprimitive_authority_mutation_during_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent mutation cannot inject behavior-bearing scalar types after inspection."""
    binding = _binding(tmp_path)
    original_check = wal_evidence.postgres_backup_artifact_evidence_was_inspected

    def mutate_after_inspection(evidence: object) -> bool:
        inspected = original_check(evidence)
        assert inspected is True
        object.__setattr__(binding, "sha256", b"not-text")
        return True

    monkeypatch.setattr(
        wal_evidence,
        "postgres_backup_artifact_evidence_was_inspected",
        mutate_after_inspection,
    )

    assert postgres_wal_segment_binding_is_valid(binding) is False


def test_validator_rejects_non_artifact_evidence_reference(tmp_path: Path) -> None:
    """A caller cannot replace the inspected artifact authority with an arbitrary object."""
    binding = _binding(tmp_path)
    object.__setattr__(binding, "artifact_evidence", object())

    assert postgres_wal_segment_binding_is_valid(binding) is False


def test_validator_rejects_malformed_artifact_scalar_types(tmp_path: Path) -> None:
    """Artifact digest fields must retain exact primitive types before provenance checks."""
    binding = _binding(tmp_path)
    object.__setattr__(binding.artifact_evidence, "sha256", b"not-text")

    assert postgres_wal_segment_binding_is_valid(binding) is False


def test_bind_rejects_non_artifact_authority() -> None:
    """Binding rejects arbitrary objects before they can reach provenance logic."""
    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^PostgreSQL WAL segment artifact evidence was not inspected$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=_SEGMENT_NAME,
            wal_segment_size_bytes=_MIB,
            artifact_evidence=object(),  # type: ignore[arg-type]
        )


def test_bind_rejects_malformed_artifact_scalars(tmp_path: Path) -> None:
    """Binding rejects mutated evidence scalars before granting copy authority."""
    artifact_path = tmp_path / "wal-segment-malformed"
    artifact_path.write_bytes(b"W" * _MIB)
    artifact = inspect_postgres_backup_artifact(
        str(artifact_path),
        maximum_size_bytes=_MIB,
    )
    object.__setattr__(artifact, "sha256", b"not-text")

    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^PostgreSQL WAL segment artifact evidence was not inspected$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=_SEGMENT_NAME,
            wal_segment_size_bytes=_MIB,
            artifact_evidence=artifact,
        )


def test_bind_rejects_artifact_mutation_during_provenance_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Binding cannot copy artifact fields changed during the provenance decision."""
    artifact_path = tmp_path / "wal-segment-bind-race"
    artifact_path.write_bytes(b"W" * _MIB)
    artifact = inspect_postgres_backup_artifact(
        str(artifact_path),
        maximum_size_bytes=_MIB,
    )
    original_check = wal_evidence.postgres_backup_artifact_evidence_was_inspected

    def mutate_after_inspection(evidence: object) -> bool:
        inspected = original_check(evidence)
        assert inspected is True
        object.__setattr__(artifact, "sha256", "F" * 64)
        return True

    monkeypatch.setattr(
        wal_evidence,
        "postgres_backup_artifact_evidence_was_inspected",
        mutate_after_inspection,
    )

    with pytest.raises(
        PostgresWalSegmentEvidenceError,
        match="^PostgreSQL WAL segment artifact evidence changed during binding$",
    ):
        bind_postgres_wal_segment_evidence(
            segment_name=_SEGMENT_NAME,
            wal_segment_size_bytes=_MIB,
            artifact_evidence=artifact,
        )
