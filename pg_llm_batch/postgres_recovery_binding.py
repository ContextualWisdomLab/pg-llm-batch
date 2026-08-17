# SPDX-License-Identifier: Apache-2.0
"""Bind packaged schema and backup-artifact evidence into one recovery receipt."""

from __future__ import annotations

import re

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
    postgres_backup_artifact_evidence_was_inspected,
)
from pg_llm_batch.postgres_recovery_receipt import (
    PostgresRecoveryReceipt,
    PostgresRecoveryReceiptError,
)
from pg_llm_batch.postgres_schema_evidence import (
    PostgresSchemaEvidence,
    postgres_schema_evidence_was_inspected,
)


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SIGNED_BIGINT = (1 << 63) - 1


class PostgresRecoveryBindingError(ValueError):
    """Report a fail-closed recovery-evidence composition violation."""


def _content_free_digest(value: object) -> bool:
    """Return whether a value is an exact lowercase SHA-256 hex digest."""
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _positive_bigint(value: object) -> bool:
    """Return whether a value is an exact positive PostgreSQL bigint."""
    return type(value) is int and 0 < value <= _MAX_SIGNED_BIGINT


def _binding_inputs_are_valid(
    package_version: object,
    source_commit: object,
    postgres_major: object,
    schema_evidence: object,
    backup_method: object,
    backup_evidence: object,
    started_at_epoch: object,
    completed_at_epoch: object,
) -> bool:
    """Return whether evidence objects are exact and internally well-formed."""
    if not (
        type(package_version) is str
        and type(source_commit) is str
        and type(postgres_major) is int
        and type(schema_evidence) is PostgresSchemaEvidence
        and type(backup_method) is str
        and type(backup_evidence) is PostgresBackupArtifactEvidence
        and type(started_at_epoch) is int
        and type(completed_at_epoch) is int
    ):
        return False
    return (
        _content_free_digest(schema_evidence.sha256)
        and _positive_bigint(schema_evidence.size_bytes)
        and _content_free_digest(backup_evidence.sha256)
        and _positive_bigint(backup_evidence.size_bytes)
        and postgres_schema_evidence_was_inspected(schema_evidence)
        and postgres_backup_artifact_evidence_was_inspected(backup_evidence)
    )


def bind_postgres_recovery_receipt(
    *,
    package_version: str,
    source_commit: str,
    postgres_major: int,
    schema_evidence: PostgresSchemaEvidence,
    backup_method: str,
    backup_evidence: PostgresBackupArtifactEvidence,
    started_at_epoch: int,
    completed_at_epoch: int,
) -> PostgresRecoveryReceipt:
    """Compose one content-free receipt from exact inspected evidence objects.

    The binder copies ``schema_sha256`` from packaged schema evidence and
    ``backup_sha256`` plus ``backup_size_bytes`` from backup-artifact evidence.
    Callers cannot supply a parallel digest or size that disagrees with those
    objects. Public dataclass construction and ``dataclasses.replace()`` copies
    are not inspection provenance. ``service_name``, filesystem paths, DSNs,
    credentials, ``tenant_scope``, and backup bytes never enter the receipt.
    ``backup_method`` remains a reviewed recovery profile label, not a tenant
    authorization boundary.
    """
    if not _binding_inputs_are_valid(
        package_version,
        source_commit,
        postgres_major,
        schema_evidence,
        backup_method,
        backup_evidence,
        started_at_epoch,
        completed_at_epoch,
    ):
        raise PostgresRecoveryBindingError(
            "invalid PostgreSQL recovery binding inputs"
        )

    try:
        return PostgresRecoveryReceipt(
            package_version=package_version,
            source_commit=source_commit,
            postgres_major=postgres_major,
            schema_sha256=schema_evidence.sha256,
            backup_method=backup_method,
            backup_sha256=backup_evidence.sha256,
            backup_size_bytes=backup_evidence.size_bytes,
            started_at_epoch=started_at_epoch,
            completed_at_epoch=completed_at_epoch,
        )
    except PostgresRecoveryReceiptError:
        raise PostgresRecoveryBindingError(
            "invalid PostgreSQL recovery binding metadata"
        ) from None
