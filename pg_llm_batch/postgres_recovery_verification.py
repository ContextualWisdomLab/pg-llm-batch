# SPDX-License-Identifier: Apache-2.0
"""Verify a stored recovery receipt by re-inspecting current schema and backup bytes."""

from __future__ import annotations

import re
import secrets

from pg_llm_batch.postgres_backup_evidence import inspect_postgres_backup_artifact
from pg_llm_batch.postgres_recovery_receipt import PostgresRecoveryReceipt
from pg_llm_batch.postgres_schema_evidence import inspect_postgres_schema


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SIGNED_BIGINT = (1 << 63) - 1


class PostgresRecoveryVerificationError(ValueError):
    """Report a fail-closed recovery-receipt verification violation."""


def _content_free_digest(value: object) -> bool:
    """Return whether a value is an exact lowercase SHA-256 hex digest."""
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _positive_bigint(value: object) -> bool:
    """Return whether a value is an exact positive PostgreSQL bigint."""
    return type(value) is int and 0 < value <= _MAX_SIGNED_BIGINT


def _receipt_is_verifiable(receipt: object) -> bool:
    """Return whether a receipt is the exact stored type with comparable fields."""
    return (
        type(receipt) is PostgresRecoveryReceipt
        and _content_free_digest(receipt.schema_sha256)
        and _content_free_digest(receipt.backup_sha256)
        and _positive_bigint(receipt.backup_size_bytes)
    )


def verify_postgres_recovery_receipt(
    receipt: PostgresRecoveryReceipt,
    *,
    backup_artifact_path: str,
) -> None:
    """Fail closed unless live inspection still matches one stored receipt.

    The verifier always calls ``inspect_postgres_schema()`` and
    ``inspect_postgres_backup_artifact(backup_artifact_path)``. It does not
    accept preconstructed ``PostgresSchemaEvidence`` or
    ``PostgresBackupArtifactEvidence`` objects, because those public
    constructors are caller claims rather than inspection provenance. Callers
    cannot supply a parallel digest, size, DSN, credential, ``service_name``,
    tenant scope, or backup-byte argument. A mismatch tells the operator to
    stop before restore and re-inspect the disagreeing object.
    """
    if not _receipt_is_verifiable(receipt) or type(backup_artifact_path) is not str:
        raise PostgresRecoveryVerificationError(
            "invalid PostgreSQL recovery verification inputs"
        )

    schema_evidence = inspect_postgres_schema()
    backup_evidence = inspect_postgres_backup_artifact(backup_artifact_path)

    if not secrets.compare_digest(receipt.schema_sha256, schema_evidence.sha256):
        raise PostgresRecoveryVerificationError(
            "inspected schema does not match recovery receipt"
        )
    if (
        not secrets.compare_digest(receipt.backup_sha256, backup_evidence.sha256)
        or receipt.backup_size_bytes != backup_evidence.size_bytes
    ):
        raise PostgresRecoveryVerificationError(
            "inspected backup does not match recovery receipt"
        )
