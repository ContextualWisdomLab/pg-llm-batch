# SPDX-License-Identifier: Apache-2.0
"""Regression tests for binding schema and backup evidence into recovery receipts."""

from __future__ import annotations

import gc
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_backup_evidence as backup_evidence_module
import pg_llm_batch.postgres_schema_evidence as schema_evidence_module
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
    """Identify a caller-controlled schema evidence subclass."""


class _HostileBackupEvidence(PostgresBackupArtifactEvidence):
    """Identify a caller-controlled backup evidence subclass."""


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


def _inspected_backup(
    tmp_path: Path, payload: bytes | None = None
) -> PostgresBackupArtifactEvidence:
    body = b"PGDMP\x01logical-fixture\x00" if payload is None else payload
    artifact = tmp_path / "tenant_export.dump"
    artifact.write_bytes(body)
    return inspect_postgres_backup_artifact(str(artifact))


def _bind(tmp_path: Path, **overrides: object) -> PostgresRecoveryReceipt:
    arguments: dict[str, object] = {
        "package_version": "0.1.0",
        "source_commit": COMMIT,
        "postgres_major": 18,
        "backup_method": "logical",
        "started_at_epoch": 1_786_800_000,
        "completed_at_epoch": 1_786_800_030,
    }
    if "schema_evidence" not in overrides:
        arguments["schema_evidence"] = inspect_postgres_schema()
    if "backup_evidence" not in overrides:
        arguments["backup_evidence"] = _inspected_backup(tmp_path)
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


def test_binder_rejects_fabricated_exact_type_evidence() -> None:
    """Do not treat public evidence dataclass construction as inspection provenance."""
    fabricated_schema = PostgresSchemaEvidence("d" * 64, 1234)
    fabricated_backup = PostgresBackupArtifactEvidence("e" * 64, 5678)

    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        bind_postgres_recovery_receipt(
            package_version="0.1.0",
            source_commit=COMMIT,
            postgres_major=18,
            schema_evidence=fabricated_schema,
            backup_method="logical",
            backup_evidence=fabricated_backup,
            started_at_epoch=1_786_800_000,
            completed_at_epoch=1_786_800_030,
        )


@pytest.mark.parametrize("method", ["logical", "physical", "pitr"])
def test_binder_copies_reviewed_backup_methods(method: str, tmp_path: Path) -> None:
    schema = inspect_postgres_schema()
    backup = _inspected_backup(tmp_path)
    receipt = _bind(
        tmp_path,
        backup_method=method,
        schema_evidence=schema,
        backup_evidence=backup,
    )

    assert receipt.backup_method == method
    assert receipt.schema_sha256 == schema.sha256
    assert receipt.backup_sha256 == backup.sha256
    assert receipt.backup_size_bytes == backup.size_bytes


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
    tmp_path: Path,
) -> None:
    with pytest.raises(PostgresRecoveryBindingError, match=f"^{message}$") as raised:
        _bind(tmp_path, **overrides)

    assert "secret" not in str(raised.value)
    assert "authorized-tenant-export" not in str(raised.value)


def test_binder_rejects_schema_subclass_before_digest_access(tmp_path: Path) -> None:
    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(tmp_path, schema_evidence=_HostileSchemaEvidence(SCHEMA_SHA256, 2048))


def test_binder_rejects_backup_subclass_before_digest_access(tmp_path: Path) -> None:
    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(tmp_path, backup_evidence=_HostileBackupEvidence(BACKUP_SHA256, 4096))


def test_binder_rejects_equal_valued_uninspected_evidence(tmp_path: Path) -> None:
    """Matching digests from public constructors are still not inspected evidence."""
    schema = inspect_postgres_schema()
    backup = _inspected_backup(tmp_path)
    fabricated_schema = PostgresSchemaEvidence(schema.sha256, schema.size_bytes)
    fabricated_backup = PostgresBackupArtifactEvidence(backup.sha256, backup.size_bytes)

    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(
            tmp_path,
            schema_evidence=fabricated_schema,
            backup_evidence=fabricated_backup,
        )


def test_binder_rejects_replaced_inspected_evidence(tmp_path: Path) -> None:
    """A field-equal copy is not the object inspect_* returned."""
    schema = inspect_postgres_schema()
    backup = _inspected_backup(tmp_path)

    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(
            tmp_path,
            schema_evidence=replace(schema),
            backup_evidence=replace(backup),
        )


def test_binder_rejects_schema_evidence_mutated_after_inspection(tmp_path: Path) -> None:
    """A frozen dataclass mutation must not preserve inspection provenance."""
    schema = inspect_postgres_schema()
    backup = _inspected_backup(tmp_path)
    object.__setattr__(schema, "sha256", "d" * 64)

    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(tmp_path, schema_evidence=schema, backup_evidence=backup)


def test_binder_rejects_backup_evidence_mutated_after_inspection(tmp_path: Path) -> None:
    """Low-level mutation must not turn unobserved backup fields into receipt truth."""
    schema = inspect_postgres_schema()
    backup = _inspected_backup(tmp_path)
    object.__setattr__(backup, "size_bytes", backup.size_bytes + 1)

    with pytest.raises(
        PostgresRecoveryBindingError,
        match="^invalid PostgreSQL recovery binding inputs$",
    ):
        _bind(tmp_path, schema_evidence=schema, backup_evidence=backup)


def test_inspection_provenance_bookkeeping_releases_dead_evidence(
    tmp_path: Path,
) -> None:
    """Repeated inspections must not accumulate stale object identities forever."""
    artifact = tmp_path / "bounded-provenance.dump"
    artifact.write_bytes(b"PGDMP\x01bounded-provenance\x00")
    schema_before = len(schema_evidence_module._INSPECTED_SCHEMA_EVIDENCE_IDS)
    backup_before = len(backup_evidence_module._INSPECTED_BACKUP_EVIDENCE_IDS)

    for _ in range(8):
        schema = inspect_postgres_schema()
        backup = inspect_postgres_backup_artifact(str(artifact))
    del schema, backup
    gc.collect()

    assert len(schema_evidence_module._INSPECTED_SCHEMA_EVIDENCE_IDS) <= schema_before
    assert len(backup_evidence_module._INSPECTED_BACKUP_EVIDENCE_IDS) <= backup_before


def test_binder_does_not_accept_a_parallel_size_that_can_disagree(
    tmp_path: Path,
) -> None:
    payload = b"PGDMP\x01size-lock\x00" + bytes(8192 - 16)
    backup = _inspected_backup(tmp_path, payload)
    receipt = _bind(tmp_path, backup_evidence=backup)
    names = bind_postgres_recovery_receipt.__code__.co_varnames

    assert len(payload) == 8192
    assert receipt.backup_size_bytes == 8192
    assert "size_bytes" not in names
    assert "schema_sha256" not in names
    assert "backup_sha256" not in names
    assert "tenant_scope" not in names
    assert "path" not in names
