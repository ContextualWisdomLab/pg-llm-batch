# SPDX-License-Identifier: Apache-2.0
"""Compose bounded PostgreSQL logical restore primitives into one recovery drill."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass

from pg_llm_batch.postgres_logical_restore import (
    PostgresLogicalRestoreResult,
    restore_postgres_logical_backup,
)
from pg_llm_batch.postgres_recovery_receipt import PostgresRecoveryReceipt
from pg_llm_batch.postgres_restore_acceptance import (
    PostgresRestoreCatalogEvidence,
    inspect_postgres_restore_catalog,
)
from pg_llm_batch.postgres_restore_target import (
    PostgresRestoreTargetIdentity,
    verify_postgres_restore_target_isolation,
)
from pg_llm_batch.postgres_schema_evidence import (
    PostgresSchemaEvidence,
    inspect_postgres_schema,
)


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_DEFAULT_MAXIMUM_ARCHIVE_SIZE_BYTES = 64 * 1024 * 1024 * 1024
_DescriptorIdentity = tuple[int, int, int, int, int, int]


class PostgresLogicalRecoveryDrillError(RuntimeError):
    """Report a fail-closed logical recovery-drill composition violation."""


@dataclass(frozen=True, slots=True)
class PostgresLogicalRecoveryDrillEvidence:
    """Represent content-free evidence from one successful isolated logical drill."""

    package_version: str
    source_commit: str
    postgres_major: int
    schema_sha256: str
    backup_sha256: str
    backup_size_bytes: int
    caller_asserted_restore_system_identifier: int
    required_table_count: int
    required_index_count: int
    lifecycle_rls_forced: bool
    checkpoint_store_present: bool
    checkpoint_store_rls_forced: bool

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable logical recovery-drill evidence schema."""
        return {
            "package_version": self.package_version,
            "source_commit": self.source_commit,
            "postgres_major": self.postgres_major,
            "schema_sha256": self.schema_sha256,
            "backup_sha256": self.backup_sha256,
            "backup_size_bytes": self.backup_size_bytes,
            "caller_asserted_restore_system_identifier": self.caller_asserted_restore_system_identifier,
            "required_table_count": self.required_table_count,
            "required_index_count": self.required_index_count,
            "lifecycle_rls_forced": self.lifecycle_rls_forced,
            "checkpoint_store_present": self.checkpoint_store_present,
            "checkpoint_store_rls_forced": self.checkpoint_store_rls_forced,
        }


def _artifact_error() -> None:
    """Reject restore bytes without reflecting path, content, or lower-layer detail."""
    raise PostgresLogicalRecoveryDrillError(
        "logical recovery drill backup artifact does not match receipt"
    )


def _descriptor_identity(status: os.stat_result) -> _DescriptorIdentity:
    """Return observable descriptor metadata used to detect in-place mutation."""
    return (
        status.st_dev,
        status.st_ino,
        stat.S_IFMT(status.st_mode),
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _verify_restore_descriptor(
    input_descriptor: int,
    receipt: PostgresRecoveryReceipt,
    maximum_archive_size_bytes: int,
) -> None:
    """Hash the exact caller-owned descriptor without changing its current offset."""
    if (
        type(input_descriptor) is not int
        or input_descriptor < 0
        or type(maximum_archive_size_bytes) is not int
        or not 1 <= maximum_archive_size_bytes <= _MAX_SIGNED_BIGINT
        or receipt.backup_size_bytes > maximum_archive_size_bytes
    ):
        _artifact_error()
    try:
        initial_status = os.fstat(input_descriptor)
    except (OSError, ValueError):
        _artifact_error()
    if (
        not stat.S_ISREG(initial_status.st_mode)
        or initial_status.st_size != receipt.backup_size_bytes
    ):
        _artifact_error()

    initial_identity = _descriptor_identity(initial_status)
    digest = hashlib.sha256()
    offset = 0
    while offset < receipt.backup_size_bytes:
        remaining = receipt.backup_size_bytes - offset
        try:
            chunk = os.pread(input_descriptor, min(_HASH_CHUNK_BYTES, remaining), offset)
        except (OSError, ValueError):
            _artifact_error()
        if type(chunk) is not bytes or not chunk or len(chunk) > remaining:
            _artifact_error()
        digest.update(chunk)
        offset += len(chunk)

    try:
        final_status = os.fstat(input_descriptor)
    except (OSError, ValueError):
        _artifact_error()
    if (
        _descriptor_identity(final_status) != initial_identity
        or digest.hexdigest() != receipt.backup_sha256
    ):
        _artifact_error()


def _verify_schema_receipt(
    receipt: PostgresRecoveryReceipt,
) -> PostgresSchemaEvidence:
    """Bind the recovery receipt to the exact currently packaged schema bytes."""
    schema = inspect_postgres_schema()
    if type(schema) is not PostgresSchemaEvidence or schema.sha256 != receipt.schema_sha256:
        raise PostgresLogicalRecoveryDrillError(
            "logical recovery drill schema evidence does not match receipt"
        )
    return schema


def _verify_catalog_evidence(
    catalog: object,
    schema: PostgresSchemaEvidence,
    receipt: PostgresRecoveryReceipt,
) -> PostgresRestoreCatalogEvidence:
    """Bind post-restore catalog evidence to the same packaged schema identity."""
    if (
        type(catalog) is not PostgresRestoreCatalogEvidence
        or catalog.expected_schema_sha256 != receipt.schema_sha256
        or catalog.expected_schema_size_bytes != schema.size_bytes
    ):
        raise PostgresLogicalRecoveryDrillError(
            "logical recovery drill catalog evidence does not match packaged schema"
        )
    return catalog


def run_postgres_logical_recovery_drill(
    receipt: PostgresRecoveryReceipt,
    input_descriptor: int,
    *,
    live_service_name: str,
    restore_service_name: str,
    live_target_identity: PostgresRestoreTargetIdentity,
    restore_target_identity: PostgresRestoreTargetIdentity,
    restore_connection: object,
    source_superusers_trusted: bool = False,
    pg_restore_executable: str,
    timeout_seconds: int = 1800,
    connect_timeout_seconds: int = 15,
    maximum_archive_size_bytes: int = _DEFAULT_MAXIMUM_ARCHIVE_SIZE_BYTES,
) -> PostgresLogicalRecoveryDrillEvidence:
    """Run one bounded logical restore drill against an already isolated target.

    The caller owns the live and restore connections, libpq service definitions,
    trusted-source decision, credential/key custody, and destruction of the recovery
    target after acceptance. The package first requires an exact logical receipt,
    binds that receipt to the currently packaged schema and exact caller-owned archive
    bytes, proves the supplied restore cluster identity differs from the live cluster,
    executes the protected single-transaction logical restore, re-hashes the archive,
    and then inspects package-owned catalog/RLS invariants through the caller-owned
    restore connection. Success is bounded content-free evidence for this one drill;
    it is not PITR, RPO/RTO, application-readiness, external-key recovery, or a
    distributed durability guarantee.
    """
    if type(receipt) is not PostgresRecoveryReceipt or receipt.backup_method != "logical":
        raise PostgresLogicalRecoveryDrillError(
            "logical recovery drill requires a logical recovery receipt"
        )

    schema = _verify_schema_receipt(receipt)
    _verify_restore_descriptor(input_descriptor, receipt, maximum_archive_size_bytes)
    verify_postgres_restore_target_isolation(
        live_service_name=live_service_name,
        restore_service_name=restore_service_name,
        live_target_identity=live_target_identity,
        restore_target_identity=restore_target_identity,
    )
    restore_result = restore_postgres_logical_backup(
        restore_service_name,
        input_descriptor,
        source_superusers_trusted=source_superusers_trusted,
        pg_restore_executable=pg_restore_executable,
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        maximum_archive_size_bytes=maximum_archive_size_bytes,
    )
    if (
        type(restore_result) is not PostgresLogicalRestoreResult
        or restore_result.size_bytes != receipt.backup_size_bytes
    ):
        raise PostgresLogicalRecoveryDrillError(
            "logical recovery drill restore result does not match receipt"
        )
    _verify_restore_descriptor(input_descriptor, receipt, maximum_archive_size_bytes)
    catalog = _verify_catalog_evidence(
        inspect_postgres_restore_catalog(restore_connection),
        schema,
        receipt,
    )
    return PostgresLogicalRecoveryDrillEvidence(
        package_version=receipt.package_version,
        source_commit=receipt.source_commit,
        postgres_major=receipt.postgres_major,
        schema_sha256=receipt.schema_sha256,
        backup_sha256=receipt.backup_sha256,
        backup_size_bytes=receipt.backup_size_bytes,
        caller_asserted_restore_system_identifier=restore_target_identity.system_identifier,
        required_table_count=catalog.required_table_count,
        required_index_count=catalog.required_index_count,
        lifecycle_rls_forced=catalog.lifecycle_rls_forced,
        checkpoint_store_present=catalog.checkpoint_store_present,
        checkpoint_store_rls_forced=catalog.checkpoint_store_rls_forced,
    )
