# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for immutable recovery-receipt verification snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

import pg_llm_batch.postgres_recovery_verification as recovery_verification
from pg_llm_batch.postgres_backup_evidence import inspect_postgres_backup_artifact
from pg_llm_batch.postgres_recovery_receipt import PostgresRecoveryReceipt
from pg_llm_batch.postgres_schema_evidence import inspect_postgres_schema


_COMMIT = "a" * 40


def _receipt(
    *,
    schema_sha256: str,
    backup_sha256: str,
    backup_size_bytes: int,
) -> PostgresRecoveryReceipt:
    """Build one structurally valid receipt with caller-selected artifact identity."""
    return PostgresRecoveryReceipt(
        package_version="0.1.0",
        source_commit=_COMMIT,
        postgres_major=18,
        schema_sha256=schema_sha256,
        backup_method="logical",
        backup_sha256=backup_sha256,
        backup_size_bytes=backup_size_bytes,
        started_at_epoch=1_786_800_000,
        completed_at_epoch=1_786_800_030,
    )


def test_schema_inspection_cannot_rewrite_validated_receipt_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-validation mutation cannot replace the receipt identity being checked."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    live_schema = inspect_postgres_schema()
    live_backup = inspect_postgres_backup_artifact(str(artifact))
    receipt = _receipt(
        schema_sha256="d" * 64,
        backup_sha256="e" * 64,
        backup_size_bytes=1,
    )

    def mutating_schema_inspection() -> object:
        object.__setattr__(receipt, "schema_sha256", live_schema.sha256)
        object.__setattr__(receipt, "backup_sha256", live_backup.sha256)
        object.__setattr__(receipt, "backup_size_bytes", live_backup.size_bytes)
        return live_schema

    monkeypatch.setattr(
        recovery_verification,
        "inspect_postgres_schema",
        mutating_schema_inspection,
    )

    with pytest.raises(
        recovery_verification.PostgresRecoveryVerificationError,
        match="^inspected schema does not match recovery receipt$",
    ):
        recovery_verification.verify_postgres_recovery_receipt(
            receipt,
            backup_artifact_path=str(artifact),
        )


def test_backup_inspection_cannot_rewrite_validated_receipt_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backup-inspection mutation cannot replace the digest or size under review."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    live_schema = inspect_postgres_schema()
    live_backup = inspect_postgres_backup_artifact(str(artifact))
    receipt = _receipt(
        schema_sha256=live_schema.sha256,
        backup_sha256="e" * 64,
        backup_size_bytes=1,
    )
    original_backup_inspection = recovery_verification.inspect_postgres_backup_artifact

    def mutating_backup_inspection(path: str) -> object:
        inspected = original_backup_inspection(path)
        object.__setattr__(receipt, "backup_sha256", live_backup.sha256)
        object.__setattr__(receipt, "backup_size_bytes", live_backup.size_bytes)
        return inspected

    monkeypatch.setattr(
        recovery_verification,
        "inspect_postgres_backup_artifact",
        mutating_backup_inspection,
    )

    with pytest.raises(
        recovery_verification.PostgresRecoveryVerificationError,
        match="^inspected backup does not match recovery receipt$",
    ):
        recovery_verification.verify_postgres_recovery_receipt(
            receipt,
            backup_artifact_path=str(artifact),
        )
