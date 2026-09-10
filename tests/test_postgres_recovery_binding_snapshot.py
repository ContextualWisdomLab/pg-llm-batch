# SPDX-License-Identifier: Apache-2.0
"""Concurrency regressions for inspected PostgreSQL recovery evidence binding."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch import postgres_recovery_binding
from pg_llm_batch.postgres_backup_evidence import inspect_postgres_backup_artifact
from pg_llm_batch.postgres_schema_evidence import inspect_postgres_schema


_SOURCE_COMMIT = "a" * 40


def _bind_receipt(
    schema_evidence: object,
    backup_evidence: object,
):
    """Bind one valid receipt while keeping mutation tests focused on provenance."""
    return postgres_recovery_binding.bind_postgres_recovery_receipt(
        package_version="0.1.0",
        source_commit=_SOURCE_COMMIT,
        postgres_major=18,
        schema_evidence=schema_evidence,  # type: ignore[arg-type]
        backup_method="logical",
        backup_evidence=backup_evidence,  # type: ignore[arg-type]
        started_at_epoch=1,
        completed_at_epoch=2,
    )


def test_backup_mutation_after_validation_cannot_rewrite_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-validation mutation cannot replace inspected backup identity."""
    backup_path = tmp_path / "backup.dump"
    backup_path.write_bytes(b"inspected-backup")
    schema_evidence = inspect_postgres_schema()
    backup_evidence = inspect_postgres_backup_artifact(str(backup_path))
    inspected_sha256 = backup_evidence.sha256
    inspected_size_bytes = backup_evidence.size_bytes
    real_validate = postgres_recovery_binding._binding_inputs_are_valid

    def mutate_after_validation(*args: object) -> bool:
        valid = real_validate(*args)
        assert valid
        object.__setattr__(backup_evidence, "sha256", "f" * 64)
        object.__setattr__(backup_evidence, "size_bytes", inspected_size_bytes + 1)
        return True

    monkeypatch.setattr(
        postgres_recovery_binding,
        "_binding_inputs_are_valid",
        mutate_after_validation,
    )

    receipt = _bind_receipt(schema_evidence, backup_evidence)

    assert receipt.backup_sha256 == inspected_sha256
    assert receipt.backup_size_bytes == inspected_size_bytes


def test_schema_mutation_after_validation_cannot_rewrite_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-validation mutation cannot replace inspected packaged-schema identity."""
    backup_path = tmp_path / "backup.dump"
    backup_path.write_bytes(b"inspected-backup")
    schema_evidence = inspect_postgres_schema()
    backup_evidence = inspect_postgres_backup_artifact(str(backup_path))
    inspected_sha256 = schema_evidence.sha256
    real_validate = postgres_recovery_binding._binding_inputs_are_valid

    def mutate_after_validation(*args: object) -> bool:
        valid = real_validate(*args)
        assert valid
        object.__setattr__(schema_evidence, "sha256", "e" * 64)
        return True

    monkeypatch.setattr(
        postgres_recovery_binding,
        "_binding_inputs_are_valid",
        mutate_after_validation,
    )

    receipt = _bind_receipt(schema_evidence, backup_evidence)

    assert receipt.schema_sha256 == inspected_sha256
