# SPDX-License-Identifier: Apache-2.0
"""Regression tests for binding schema and backup evidence into recovery receipts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
    inspect_postgres_backup_artifact,
)
from pg_llm_batch.postgres_recovery_binding import (
    PostgresRecoveryBindingError,
    bind_postgres_recovery_receipt,
)
from pg_llm_batch.postgres_recovery_receipt import PostgresRecoveryReceipt
from pg_llm_batch.postgres_schema_evidence import (
    PostgresSchemaEvidence,
    inspect_postgres_schema,
)


COMMIT = "a" * 40
SCHEMA_SHA256 = "b" * 64
BACKUP_SHA256 = "c" * 64


class _HostileSchemaEvidence(PostgresSchemaEvidence):
    """Override digest access after a caller-controlled subclass is accepted."""

    @property
    def sha256(self) -> str:  # type: ignore[override]
        raise AssertionError("hostile schema digest must not execute")


class _HostileBackupEvidence(PostgresBackupArtifactEvidence):
    """Override digest access after a caller-controlled subclass is accepted."""

    @property
    def sha256(self) -> str:  # type: ignore[override]
        raise AssertionError("hostile backup digest must not execute")


class _HostileString(str):
    """Refuse rendering if a string subclass leaks into receipt construction."""

    def __str__(self) -> str:
        raise AssertionError("must not render hostile binding metadata")


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


def _bind(**overrides: object) -> PostgresRecoveryReceipt:
    arguments: dict[str, object] = {
        "package_version": "0.1.0",
        "source_commit": COMMIT,
        "postgres_major": 18,
        "schema_evidence": _schema_evidence(),
        "backup_method": "logical",
        "backup_evidence": _backup_evidence(),
        "started_at_epoch": 1_786_800_000,
        "completed_at_epoch": 1_786_800_030,
    }
    arguments.update(overrides)
    return bind_postgres_recovery_receipt(**arguments)  # type: ignore[arg-type]


def test_binder_reproduces_true_schema_and_artifact_digests(tmp_path: Path) -> None:
    """Copy exact inspected digests so a receipt cannot disagree with hashed bytes."""
    payload = b"PGDMP\x01authorized-tenant-export\x00"
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(payload)
    schema = inspect_postgres_schema()
    backup = inspect_postgres_backup_artifact(str(artifact))

    receipt = bind_postgres_recovery_receipt(
        package_version="0.1.0",
        source_commit=COMMIT,
        postgres_major=18,
        schema_evidence=schema,
        backup_method="logical",
        backup_evidence=backup,
        started_at_epoch=1_786_800_000,
        completed_at_epoch=1_786_800_030,
    )

    assert receipt.schema_sha256 == schema.sha256
    assert receipt.backup_sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.backup_sha256 == backup.sha256
    assert receipt.backup_size_bytes == len(payload)
    encoded = receipt.to_json()
    assert "authorized-tenant-export" not in encoded
    assert str(artifact) not in encoded
    assert "postgresql://" not in encoded


@pytest.mark.parametrize("method", ["logical", "physical", "pitr"])
def test_binder_copies_reviewed_backup_methods(method: str) -> None:
    receipt = _bind(backup_method=method)

    assert receipt.backup_method == method
    assert receipt.schema_sha256 == SCHEMA_SHA256
    assert receipt.backup_sha256 == BACKUP_SHA256
    assert receipt.backup_size_bytes == 4096


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"package_version": b"0.1.0"}, "invalid PostgreSQL recovery binding inputs"),
        ({"source_commit": bytearray(COMMIT, "ascii")}, "invalid PostgreSQL recovery binding inputs"),
        ({"postgres_major": True}, "invalid PostgreSQL recovery binding inputs"),
        ({"schema_evidence": SimpleNamespace(sha256=SCHEMA_SHA256, size_bytes=2048)}, "invalid PostgreSQL recovery binding inputs"),
        ({"backup_method": _HostileString("logical")}, "invalid PostgreSQL recovery binding inputs"),
        ({"backup_evidence": SimpleNamespace(sha256=BACKUP_SHA256, size_bytes=4096)}, "invalid PostgreSQL recovery binding inputs"),
        ({"started_at_epoch": True}, "invalid PostgreSQL recovery binding inputs"),
        ({"completed_at_epoch": 1.5}, "invalid PostgreSQL recovery binding inputs"),
        ({"schema_evidence": _schema_evidence(sha256="B" * 64)}, "invalid PostgreSQL recovery binding inputs"),
        ({"schema_evidence": _schema_evidence(sha256=_HostileString(SCHEMA_SHA256))}, "invalid PostgreSQL recovery binding inputs"),
        ({"schema_evidence": _schema_evidence(size_bytes=0)}, "invalid PostgreSQL recovery binding inputs"),
        ({"schema_evidence": _schema_evidence(size_bytes=True)}, "invalid PostgreSQL recovery binding inputs"),
        ({"backup_evidence": _backup_evidence(sha256="g" * 64)}, "invalid PostgreSQL recovery binding inputs"),
        ({"backup_evidence": _backup_evidence(size_bytes=1 << 63)}, "invalid PostgreSQL recovery binding inputs"),
        ({"backup_evidence": _backup_evidence(size_bytes=-1)}, "invalid PostgreSQL recovery binding inputs"),
        ({"package_version": ""}, "invalid PostgreSQL recovery binding metadata"),
        ({"package_version": "1/secret"}, "invalid PostgreSQL recovery binding metadata"),
        ({"source_commit": "abc"}, "invalid PostgreSQL recovery binding metadata"),
        ({"postgres_major": 0}, "invalid PostgreSQL recovery binding metadata"),
        ({"postgres_major": 100}, "invalid PostgreSQL recovery binding metadata"),
        ({"backup_method": "snapshot"}, "invalid PostgreSQL recovery binding metadata"),
        ({"started_at_epoch": -1}, "invalid PostgreSQL recovery binding metadata"),
        ({"completed_at_epoch": 1_786_799_999}, "invalid PostgreSQL recovery binding metadata"),
    ],
)
def test_binder_rejects_untrusted_inputs_without_reflection(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(PostgresRecoveryBindingError, match=f"^{message}$") as raised:
        _bind(**overrides)

    assert "secret" not in str(raised.value)
    assert "authorized-tenant-export" not in str(raised.value)


def test_binder_rejects_schema_subclass_before_digest_access() -> None:
    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(schema_evidence=_HostileSchemaEvidence(SCHEMA_SHA256, 2048))


def test_binder_rejects_backup_subclass_before_digest_access() -> None:
    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(backup_evidence=_HostileBackupEvidence(BACKUP_SHA256, 4096))


def test_binder_does_not_accept_a_parallel_size_that_can_disagree() -> None:
    receipt = _bind(backup_evidence=_backup_evidence(size_bytes=8192))

    assert receipt.backup_size_bytes == 8192
    assert "size_bytes" not in bind_postgres_recovery_receipt.__code__.co_varnames
