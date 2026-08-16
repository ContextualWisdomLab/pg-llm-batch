# SPDX-License-Identifier: Apache-2.0
"""Regression tests for verifying stored receipts against inspected evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
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
SCHEMA_SHA256 = "b" * 64
BACKUP_SHA256 = "c" * 64
OTHER_SCHEMA_SHA256 = "d" * 64
OTHER_BACKUP_SHA256 = "e" * 64


class _HostileReceipt(PostgresRecoveryReceipt):
    """Identify a caller-controlled recovery receipt subclass."""


class _HostileSchemaEvidence(PostgresSchemaEvidence):
    """Identify a caller-controlled schema evidence subclass."""


class _HostileBackupEvidence(PostgresBackupArtifactEvidence):
    """Identify a caller-controlled backup evidence subclass."""


def _schema_evidence(**overrides: object) -> PostgresSchemaEvidence:
    arguments: dict[str, object] = {
        "sha256": SCHEMA_SHA256,
        "size_bytes": 2048,
    }
    arguments.update(overrides)
    return PostgresSchemaEvidence(**arguments)  # type: ignore[arg-type]


def _backup_evidence(**overrides: object) -> PostgresBackupArtifactEvidence:
    arguments: dict[str, object] = {
        "sha256": BACKUP_SHA256,
        "size_bytes": 4096,
    }
    arguments.update(overrides)
    return PostgresBackupArtifactEvidence(**arguments)  # type: ignore[arg-type]


def _receipt(**overrides: object) -> PostgresRecoveryReceipt:
    arguments: dict[str, object] = {
        "package_version": "0.1.0",
        "source_commit": COMMIT,
        "postgres_major": 18,
        "schema_sha256": SCHEMA_SHA256,
        "backup_method": "logical",
        "backup_sha256": BACKUP_SHA256,
        "backup_size_bytes": 4096,
        "started_at_epoch": 1_786_800_000,
        "completed_at_epoch": 1_786_800_030,
    }
    arguments.update(overrides)
    return PostgresRecoveryReceipt(**arguments)  # type: ignore[arg-type]


def _verify(**overrides: object) -> None:
    arguments: dict[str, object] = {
        "receipt": _receipt(),
        "schema_evidence": _schema_evidence(),
        "backup_evidence": _backup_evidence(),
    }
    arguments.update(overrides)
    verify_postgres_recovery_receipt(**arguments)  # type: ignore[arg-type]


def test_verifier_accepts_true_inspected_schema_and_artifact(tmp_path: Path) -> None:
    """Accept a receipt only when re-inspected digests and size still match."""
    payload = b"PGDMP\x01authorized-tenant-export\x00"
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(payload)
    schema = inspect_postgres_schema()
    backup = inspect_postgres_backup_artifact(str(artifact))
    receipt = PostgresRecoveryReceipt(
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

    verify_postgres_recovery_receipt(
        receipt,
        schema_evidence=schema,
        backup_evidence=backup,
    )
    parsed = parse_postgres_recovery_receipt(receipt.to_json())
    verify_postgres_recovery_receipt(
        parsed,
        schema_evidence=schema,
        backup_evidence=backup,
    )

    assert receipt.backup_sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.backup_size_bytes == len(payload)
    encoded = receipt.to_json()
    assert "authorized-tenant-export" not in encoded
    assert str(artifact) not in encoded
    assert "postgresql://" not in encoded


def test_verifier_rejects_mutated_backup_bytes_before_restore(tmp_path: Path) -> None:
    """Fail closed when the stored artifact no longer hashes to the receipt."""
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(b"PGDMP\x01authorized-tenant-export\x00")
    schema = inspect_postgres_schema()
    original = inspect_postgres_backup_artifact(str(artifact))
    receipt = PostgresRecoveryReceipt(
        package_version="0.1.0",
        source_commit=COMMIT,
        postgres_major=18,
        schema_sha256=schema.sha256,
        backup_method="logical",
        backup_sha256=original.sha256,
        backup_size_bytes=original.size_bytes,
        started_at_epoch=1_786_800_000,
        completed_at_epoch=1_786_800_030,
    )
    artifact.write_bytes(b"PGDMP\x01mutated-tenant-export\x00")
    mutated = inspect_postgres_backup_artifact(str(artifact))

    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^backup evidence does not match recovery receipt$",
    ) as raised:
        verify_postgres_recovery_receipt(
            receipt,
            schema_evidence=schema,
            backup_evidence=mutated,
        )

    assert "authorized-tenant-export" not in str(raised.value)
    assert "mutated-tenant-export" not in str(raised.value)
    assert original.sha256 != mutated.sha256


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"receipt": SimpleNamespace(schema_sha256=SCHEMA_SHA256, backup_sha256=BACKUP_SHA256, backup_size_bytes=4096)}, "invalid PostgreSQL recovery verification inputs"),
        ({"schema_evidence": SimpleNamespace(sha256=SCHEMA_SHA256, size_bytes=2048)}, "invalid PostgreSQL recovery verification inputs"),
        ({"backup_evidence": SimpleNamespace(sha256=BACKUP_SHA256, size_bytes=4096)}, "invalid PostgreSQL recovery verification inputs"),
        ({"schema_evidence": _schema_evidence(sha256="B" * 64)}, "invalid PostgreSQL recovery verification inputs"),
        ({"schema_evidence": _schema_evidence(size_bytes=0)}, "invalid PostgreSQL recovery verification inputs"),
        ({"backup_evidence": _backup_evidence(sha256="g" * 64)}, "invalid PostgreSQL recovery verification inputs"),
        ({"backup_evidence": _backup_evidence(size_bytes=1 << 63)}, "invalid PostgreSQL recovery verification inputs"),
        ({"schema_evidence": _schema_evidence(sha256=OTHER_SCHEMA_SHA256)}, "schema evidence does not match recovery receipt"),
        ({"backup_evidence": _backup_evidence(sha256=OTHER_BACKUP_SHA256)}, "backup evidence does not match recovery receipt"),
        ({"backup_evidence": _backup_evidence(size_bytes=8192)}, "backup evidence does not match recovery receipt"),
    ],
)
def test_verifier_rejects_untrusted_or_disagreeing_inputs_without_reflection(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(PostgresRecoveryVerificationError, match=f"^{message}$") as raised:
        _verify(**overrides)

    assert "secret" not in str(raised.value)
    assert "authorized-tenant-export" not in str(raised.value)


def test_verifier_rejects_receipt_subclass_before_digest_compare() -> None:
    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^invalid PostgreSQL recovery verification inputs$",
    ):
        _verify(
            receipt=_HostileReceipt(
                package_version="0.1.0",
                source_commit=COMMIT,
                postgres_major=18,
                schema_sha256=SCHEMA_SHA256,
                backup_method="logical",
                backup_sha256=BACKUP_SHA256,
                backup_size_bytes=4096,
                started_at_epoch=1_786_800_000,
                completed_at_epoch=1_786_800_030,
            )
        )


def test_verifier_rejects_schema_subclass_before_digest_compare() -> None:
    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^invalid PostgreSQL recovery verification inputs$",
    ):
        _verify(schema_evidence=_HostileSchemaEvidence(SCHEMA_SHA256, 2048))


def test_verifier_rejects_backup_subclass_before_digest_compare() -> None:
    with pytest.raises(
        PostgresRecoveryVerificationError,
        match="^invalid PostgreSQL recovery verification inputs$",
    ):
        _verify(backup_evidence=_HostileBackupEvidence(BACKUP_SHA256, 4096))


def test_verifier_does_not_accept_parallel_digest_or_tenant_arguments() -> None:
    names = verify_postgres_recovery_receipt.__code__.co_varnames

    assert "schema_sha256" not in names
    assert "backup_sha256" not in names
    assert "size_bytes" not in names
    assert "tenant_scope" not in names
    assert "path" not in names
    _verify()
