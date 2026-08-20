# SPDX-License-Identifier: Apache-2.0
"""Bind packaged schema and backup-artifact evidence into one recovery receipt."""

from __future__ import annotations

import re

import pg_llm_batch.postgres_backup_evidence as backup_evidence_module
import pg_llm_batch.postgres_schema_evidence as schema_evidence_module
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


def _schema_inspection_snapshot(evidence: object) -> tuple[str, int] | None:
    """Return immutable packaged-schema fields captured by a valid inspection."""
    if not postgres_schema_evidence_was_inspected(evidence):
        return None
    observed = schema_evidence_module._INSPECTED_SCHEMA_EVIDENCE_IDS[id(evidence)]
    return observed[1], observed[2]


def _backup_inspection_snapshot(evidence: object) -> tuple[str, int] | None:
    """Return immutable backup-artifact fields captured by a valid inspection."""
    if not postgres_backup_artifact_evidence_was_inspected(evidence):
        return None
    observed = backup_evidence_module._INSPECTED_BACKUP_EVIDENCE_IDS[id(evidence)]
    return observed[1], observed[2]


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

    The binder snapshots ``schema_sha256`` from packaged schema inspection
    provenance and ``backup_sha256`` plus ``backup_size_bytes`` from backup
    inspection provenance before validating the caller-visible evidence fields.
    Later object mutation therefore cannot replace the inspected identity copied
    into a receipt. Callers cannot supply a parallel digest or size that
    disagrees with those snapshots. Public dataclass construction and
    ``dataclasses.replace()`` copies are not inspection provenance.
    ``service_name``, filesystem paths, DSNs, credentials, ``tenant_scope``, and
    backup bytes never enter the receipt. ``backup_method`` remains a reviewed
    recovery profile label, not a tenant authorization boundary.
    """
    schema_snapshot = _schema_inspection_snapshot(schema_evidence)
    backup_snapshot = _backup_inspection_snapshot(backup_evidence)
    if (
        schema_snapshot is None
        or backup_snapshot is None
        or not _binding_inputs_are_valid(
            package_version,
            source_commit,
            postgres_major,
            schema_evidence,
            backup_method,
            backup_evidence,
            started_at_epoch,
            completed_at_epoch,
        )
    ):
        raise PostgresRecoveryBindingError(
            "invalid PostgreSQL recovery binding inputs"
        )

    try:
        return PostgresRecoveryReceipt(
            package_version=package_version,
            source_commit=source_commit,
            postgres_major=postgres_major,
            schema_sha256=schema_snapshot[0],
            backup_method=backup_method,
            backup_sha256=backup_snapshot[0],
            backup_size_bytes=backup_snapshot[1],
            started_at_epoch=started_at_epoch,
            completed_at_epoch=completed_at_epoch,
        )
    except PostgresRecoveryReceiptError:
        raise PostgresRecoveryBindingError(
            "invalid PostgreSQL recovery binding metadata"
        ) from None
