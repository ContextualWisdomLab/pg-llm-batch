# SPDX-License-Identifier: Apache-2.0
"""Verify a stored recovery receipt against exact inspected evidence."""

from __future__ import annotations

import re
import secrets

from pg_llm_batch.postgres_backup_evidence import PostgresBackupArtifactEvidence
from pg_llm_batch.postgres_recovery_receipt import PostgresRecoveryReceipt
from pg_llm_batch.postgres_schema_evidence import PostgresSchemaEvidence


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


def _verification_inputs_are_valid(
    receipt: object,
    schema_evidence: object,
    backup_evidence: object,
) -> bool:
    """Return whether receipt and evidence objects are exact and well-formed."""
    if not (
        type(receipt) is PostgresRecoveryReceipt
        and type(schema_evidence) is PostgresSchemaEvidence
        and type(backup_evidence) is PostgresBackupArtifactEvidence
    ):
        return False
    return (
        _content_free_digest(receipt.schema_sha256)
        and _content_free_digest(receipt.backup_sha256)
        and _positive_bigint(receipt.backup_size_bytes)
        and _content_free_digest(schema_evidence.sha256)
        and _positive_bigint(schema_evidence.size_bytes)
        and _content_free_digest(backup_evidence.sha256)
        and _positive_bigint(backup_evidence.size_bytes)
    )


def verify_postgres_recovery_receipt(
    receipt: PostgresRecoveryReceipt,
    *,
    schema_evidence: PostgresSchemaEvidence,
    backup_evidence: PostgresBackupArtifactEvidence,
) -> None:
    """Fail closed unless inspected evidence still matches one stored receipt.

    The verifier compares ``schema_sha256`` to packaged schema evidence and
    ``backup_sha256`` plus ``backup_size_bytes`` to backup-artifact evidence.
    Callers cannot supply a parallel digest, size, path, DSN, credential,
    ``service_name``, tenant scope, or backup-byte argument. A mismatch tells
    the operator to re-inspect the disagreeing object and stop before restore.
    """
    if not _verification_inputs_are_valid(
        receipt,
        schema_evidence,
        backup_evidence,
    ):
        raise PostgresRecoveryVerificationError(
            "invalid PostgreSQL recovery verification inputs"
        )

    if not secrets.compare_digest(receipt.schema_sha256, schema_evidence.sha256):
        raise PostgresRecoveryVerificationError(
            "schema evidence does not match recovery receipt"
        )
    if (
        not secrets.compare_digest(receipt.backup_sha256, backup_evidence.sha256)
        or receipt.backup_size_bytes != backup_evidence.size_bytes
    ):
        raise PostgresRecoveryVerificationError(
            "backup evidence does not match recovery receipt"
        )
