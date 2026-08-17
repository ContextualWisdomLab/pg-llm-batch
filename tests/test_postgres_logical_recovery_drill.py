# SPDX-License-Identifier: Apache-2.0
"""Regression contract for the bounded isolated PostgreSQL logical recovery drill."""

from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace

import pytest

from pg_llm_batch.postgres_logical_restore import PostgresLogicalRestoreResult
from pg_llm_batch.postgres_recovery_receipt import PostgresRecoveryReceipt
from pg_llm_batch.postgres_restore_acceptance import PostgresRestoreCatalogEvidence
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity
from pg_llm_batch.postgres_logical_recovery_drill import (
    PostgresLogicalRecoveryDrillError,
    run_postgres_logical_recovery_drill,
)


_SCHEMA_SHA = "a" * 64
_SCHEMA_SIZE = 4096
_SOURCE_COMMIT = "b" * 40


def _receipt(payload: bytes, *, backup_method: str = "logical") -> PostgresRecoveryReceipt:
    return PostgresRecoveryReceipt(
        package_version="0.1.0",
        source_commit=_SOURCE_COMMIT,
        postgres_major=18,
        schema_sha256=_SCHEMA_SHA,
        backup_method=backup_method,
        backup_sha256=hashlib.sha256(payload).hexdigest(),
        backup_size_bytes=len(payload),
        started_at_epoch=1_800_000_000,
        completed_at_epoch=1_800_000_010,
    )


def _catalog() -> PostgresRestoreCatalogEvidence:
    return PostgresRestoreCatalogEvidence(
        required_table_count=11,
        required_index_count=2,
        lifecycle_rls_enabled=True,
        lifecycle_rls_forced=True,
        checkpoint_store_present=True,
        checkpoint_store_rls_forced=True,
        expected_schema_sha256=_SCHEMA_SHA,
        expected_schema_size_bytes=_SCHEMA_SIZE,
    )


def _private_archive(tmp_path, payload: bytes) -> int:
    path = tmp_path / "recovery.dump"
    path.write_bytes(payload)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY)


def test_logical_recovery_drill_composes_isolation_restore_and_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    payload = b"PGDMP\x01\x0f isolated recovery fixture"
    receipt = _receipt(payload)
    descriptor = _private_archive(tmp_path, payload)
    live_identity = PostgresRestoreTargetIdentity(system_identifier=11)
    restore_identity = PostgresRestoreTargetIdentity(system_identifier=22)
    calls: list[str] = []

    import pg_llm_batch.postgres_logical_recovery_drill as drill

    monkeypatch.setattr(
        drill,
        "inspect_postgres_schema",
        lambda: SimpleNamespace(sha256=_SCHEMA_SHA, size_bytes=_SCHEMA_SIZE),
    )

    def verify_target(**kwargs: object) -> None:
        assert kwargs == {
            "live_service_name": "live-db",
            "restore_service_name": "restore-db",
            "live_target_identity": live_identity,
            "restore_target_identity": restore_identity,
        }
        calls.append("isolation")

    def restore(service_name: str, input_descriptor: int, **kwargs: object):
        assert service_name == "restore-db"
        assert input_descriptor == descriptor
        assert kwargs["source_superusers_trusted"] is True
        assert kwargs["pg_restore_executable"] == "/usr/bin/pg_restore"
        calls.append("restore")
        return PostgresLogicalRestoreResult(size_bytes=len(payload))

    def inspect_catalog(connection: object) -> PostgresRestoreCatalogEvidence:
        assert connection is restore_connection
        calls.append("catalog")
        return _catalog()

    restore_connection = object()
    monkeypatch.setattr(drill, "verify_postgres_restore_target_isolation", verify_target)
    monkeypatch.setattr(drill, "restore_postgres_logical_backup", restore)
    monkeypatch.setattr(drill, "inspect_postgres_restore_catalog", inspect_catalog)

    try:
        evidence = run_postgres_logical_recovery_drill(
            receipt,
            descriptor,
            live_service_name="live-db",
            restore_service_name="restore-db",
            live_target_identity=live_identity,
            restore_target_identity=restore_identity,
            restore_connection=restore_connection,
            source_superusers_trusted=True,
            pg_restore_executable="/usr/bin/pg_restore",
        )
    finally:
        os.close(descriptor)

    assert calls == ["isolation", "restore", "catalog"]
    assert evidence.as_dict() == {
        "package_version": "0.1.0",
        "source_commit": _SOURCE_COMMIT,
        "postgres_major": 18,
        "schema_sha256": _SCHEMA_SHA,
        "backup_sha256": receipt.backup_sha256,
        "backup_size_bytes": len(payload),
        "restore_system_identifier": 22,
        "required_table_count": 11,
        "required_index_count": 2,
        "lifecycle_rls_forced": True,
        "checkpoint_store_present": True,
        "checkpoint_store_rls_forced": True,
    }


def test_logical_recovery_drill_rejects_non_logical_receipt_before_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    payload = b"physical profile must not enter logical restore"
    descriptor = _private_archive(tmp_path, payload)
    called = False

    import pg_llm_batch.postgres_logical_recovery_drill as drill

    def restore(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(drill, "restore_postgres_logical_backup", restore)
    try:
        with pytest.raises(
            PostgresLogicalRecoveryDrillError,
            match="logical recovery drill requires a logical recovery receipt",
        ):
            run_postgres_logical_recovery_drill(
                _receipt(payload, backup_method="physical"),
                descriptor,
                live_service_name="live-db",
                restore_service_name="restore-db",
                live_target_identity=PostgresRestoreTargetIdentity(system_identifier=11),
                restore_target_identity=PostgresRestoreTargetIdentity(system_identifier=22),
                restore_connection=object(),
                source_superusers_trusted=True,
                pg_restore_executable="/usr/bin/pg_restore",
            )
    finally:
        os.close(descriptor)

    assert called is False
