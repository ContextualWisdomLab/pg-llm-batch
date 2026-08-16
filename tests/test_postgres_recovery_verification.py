# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for live-inspect recovery-receipt verification."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
    PostgresBackupEvidenceError,
    inspect_postgres_backup_artifact,
)
from pg_llm_batch.postgres_recovery_receipt import (
    PostgresRecoveryReceipt,
    parse_postgres_recovery_receipt,
)
from pg_llm_batch.postgres_recovery_verification import (
    PostgresRecoveryVerificationError,
    verify_postgres_recovery_receipt,
)
from pg_llm_batch.postgres_schema_evidence import (
    PostgresSchemaEvidence,
    inspect_postgres_schema,
)


COMMIT = "a" * 40
BACKUP_SHA256 = "c" * 64


class _HostileReceipt(PostgresRecoveryReceipt):
    """Identify a caller-controlled recovery receipt subclass."""


def _receipt(**overrides: object) -> PostgresRecoveryReceipt:
    schema = inspect_postgres_schema()
    arguments: dict[str, object] = {
        "package_version": "0.1.0",
        "source_commit": COMMIT,
        "postgres_major": 18,
        "schema_sha256": schema.sha256,
        "backup_method": "logical",
        "backup_sha256": BACKUP_SHA256,
        "backup_size_bytes": 4096,
        "started_at_epoch": 1_786_800_000,
        "completed_at_epoch": 1_786_800_030,
    }
    arguments.update(overrides)
    return PostgresRecoveryReceipt(**arguments)  # type: ignore[arg-type]


def _receipt_for_artifact(artifact: Path) -> PostgresRecoveryReceipt:
    schema = inspect_postgres_schema()
    backup = inspect_postgres_backup_artifact(str(artifact))
    return PostgresRecoveryReceipt(
        package_version="0.1.0",
        source_commit=COMMIT,
        postgres_major=18,
        schema_sha256=schema.sha256,
        backup_method="logical",
        backup_sha256=backup.sha256,
        backup_size_bytes=backup.size_bytes,
        started_at_epoch=1_786_800_000,
        completed_at_epoch=1_786_800_030,
    )


def test_verifier_accepts_receipt_only_after_live_reinspection(tmp_path: Path) -> None:
    """A realistic custom-format dump must still match after parse and re-hash."""
    payload = b"PGDMP\x01authorized-tenant-export\x00"
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(payload)
    receipt = _receipt_for_artifact(artifact)

    verify_postgres_recovery_receipt(
        receipt,
        backup_artifact_path=str(artifact),
    )
    parsed = parse_postgres_recovery_receipt(receipt.to_json())
    verify_postgres_recovery_receipt(
        parsed,
        backup_artifact_path=str(artifact),
    )

    assert receipt.backup_sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.backup_size_bytes == len(payload)
    encoded = receipt.to_json()
    assert "authorized-tenant-export" not in encoded
    assert str(artifact) not in encoded
    assert "postgresql://" not in encoded


def test_verifier_rejects_mutated_backup_bytes_before_restore(tmp_path: Path) -> None:
    """Fail closed when current artifact bytes no longer hash to the receipt."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    receipt = _receipt_for_artifact(artifact)
    artifact.write_bytes(b"PGDMP\x01mutated-tenant-export\x00")

    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^inspected backup does not match recovery receipt$",
    ) as raised:
        verify_postgres_recovery_receipt(
            receipt,
            backup_artifact_path=str(artifact),
        )

    assert "authorized-tenant-export" not in str(raised.value)
    assert "mutated-tenant-export" not in str(raised.value)
    assert str(artifact) not in str(raised.value)


def test_fabricated_exact_type_evidence_cannot_replace_live_inspection(
    tmp_path: Path,
) -> None:
    """Exact-type evidence objects are caller claims, not inspection provenance."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    receipt = _receipt_for_artifact(artifact)
    other = tmp_path / "other_export.dump"
    other.write_bytes(b"PGDMP\x01other-tenant-export\x00")
    fabricated_schema = PostgresSchemaEvidence(
        sha256=receipt.schema_sha256,
        size_bytes=inspect_postgres_schema().size_bytes,
    )
    fabricated_backup = PostgresBackupArtifactEvidence(
        sha256=receipt.backup_sha256,
        size_bytes=receipt.backup_size_bytes,
    )
    parameters = inspect.signature(verify_postgres_recovery_receipt).parameters

    assert "schema_evidence" not in parameters
    assert "backup_evidence" not in parameters
    with pytest.raises(TypeError):
        verify_postgres_recovery_receipt(
            receipt,
            schema_evidence=fabricated_schema,
            backup_evidence=fabricated_backup,
        )
    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^inspected backup does not match recovery receipt$",
    ):
        verify_postgres_recovery_receipt(
            receipt,
            backup_artifact_path=str(other),
        )


def test_verifier_rejects_wrong_schema_digest_after_live_schema_inspect(
    tmp_path: Path,
) -> None:
    """A receipt that names a different packaged schema cannot pass verification."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    backup = inspect_postgres_backup_artifact(str(artifact))
    receipt = _receipt(
        schema_sha256="d" * 64,
        backup_sha256=backup.sha256,
        backup_size_bytes=backup.size_bytes,
    )

    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^inspected schema does not match recovery receipt$",
    ) as raised:
        verify_postgres_recovery_receipt(
            receipt,
            backup_artifact_path=str(artifact),
        )
    assert "d" * 64 not in str(raised.value)


def test_missing_artifact_propagates_inspector_error(tmp_path: Path) -> None:
    """Verification must observe the artifact; it cannot succeed on a missing file."""
    missing = tmp_path / "missing_export.dump"
    receipt = _receipt()

    with pytest.raises(PostgresBackupEvidenceError) as raised:
        verify_postgres_recovery_receipt(
            receipt,
            backup_artifact_path=str(missing),
        )
    assert str(missing) not in str(raised.value)
    assert "secret" not in str(raised.value)


def test_verifier_rejects_receipt_subclass_before_filesystem_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subclassed receipts are not stored evidence and must not open the artifact."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    opened = False

    def forbidden_inspect(path: str, **_kwargs: object) -> object:
        nonlocal opened
        del path
        opened = True
        raise AssertionError("hostile receipt must not inspect the artifact")

    monkeypatch.setattr(
        "pg_llm_batch.postgres_recovery_verification.inspect_postgres_backup_artifact",
        forbidden_inspect,
    )
    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^invalid PostgreSQL recovery verification inputs$",
    ):
        verify_postgres_recovery_receipt(
            _HostileReceipt(
                package_version="0.1.0",
                source_commit=COMMIT,
                postgres_major=18,
                schema_sha256=inspect_postgres_schema().sha256,
                backup_method="logical",
                backup_sha256=BACKUP_SHA256,
                backup_size_bytes=4096,
                started_at_epoch=1_786_800_000,
                completed_at_epoch=1_786_800_030,
            ),
            backup_artifact_path=str(artifact),
        )
    assert opened is False


@pytest.mark.parametrize(
    "receipt",
    [
        SimpleNamespace(
            schema_sha256="b" * 64,
            backup_sha256=BACKUP_SHA256,
            backup_size_bytes=4096,
        ),
        "not-a-receipt",
    ],
)
def test_verifier_rejects_non_receipt_inputs_before_inspect(
    receipt: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Namespace substitutes are not stored receipts."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    opened = False

    def forbidden_inspect(path: str, **_kwargs: object) -> object:
        nonlocal opened
        del path
        opened = True
        raise AssertionError("invalid receipt must not inspect the artifact")

    monkeypatch.setattr(
        "pg_llm_batch.postgres_recovery_verification.inspect_postgres_backup_artifact",
        forbidden_inspect,
    )
    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^invalid PostgreSQL recovery verification inputs$",
    ) as raised:
        verify_postgres_recovery_receipt(
            receipt,  # type: ignore[arg-type]
            backup_artifact_path=str(artifact),
        )
    assert opened is False
    assert "secret" not in str(raised.value)


def test_verifier_rejects_non_string_artifact_path_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Path objects and subclasses are not caller-owned artifact authority."""
    opened = False

    def forbidden_inspect(path: object, **_kwargs: object) -> object:
        nonlocal opened
        del path
        opened = True
        raise AssertionError("invalid path must not reach the inspector")

    monkeypatch.setattr(
        "pg_llm_batch.postgres_recovery_verification.inspect_postgres_backup_artifact",
        forbidden_inspect,
    )
    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^invalid PostgreSQL recovery verification inputs$",
    ):
        verify_postgres_recovery_receipt(
            _receipt(),
            backup_artifact_path=Path("tenant_export.dump"),  # type: ignore[arg-type]
        )
    assert opened is False


def test_verifier_does_not_accept_parallel_digest_or_tenant_arguments(
    tmp_path: Path,
) -> None:
    """Callers cannot inject digest, tenant, or prebuilt evidence arguments."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    names = verify_postgres_recovery_receipt.__code__.co_varnames
    parameters = inspect.signature(verify_postgres_recovery_receipt).parameters

    assert "schema_sha256" not in names
    assert "backup_sha256" not in names
    assert "schema_evidence" not in parameters
    assert "backup_evidence" not in parameters
    assert "tenant_scope" not in names
    verify_postgres_recovery_receipt(
        _receipt_for_artifact(artifact),
        backup_artifact_path=str(artifact),
    )
