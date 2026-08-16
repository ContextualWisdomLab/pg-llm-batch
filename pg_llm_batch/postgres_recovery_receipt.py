# SPDX-License-Identifier: Apache-2.0
"""Build bounded, content-free PostgreSQL backup evidence receipts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}\Z")
_BACKUP_METHODS = frozenset({"logical", "physical", "pitr"})
_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "package_version",
        "source_commit",
        "postgres_major",
        "schema_sha256",
        "backup_method",
        "backup_sha256",
        "backup_size_bytes",
        "started_at_epoch",
        "completed_at_epoch",
    }
)
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_MAX_RECEIPT_JSON_BYTES = 2048


class PostgresRecoveryReceiptError(ValueError):
    """Report invalid bounded PostgreSQL recovery evidence metadata."""


def _plain_text_matches(value: object, pattern: re.Pattern[str]) -> bool:
    """Return whether a value is an exact built-in string matching a pattern."""
    return type(value) is str and pattern.fullmatch(value) is not None


def _plain_backup_method(value: object) -> bool:
    """Return whether a value is one supported exact built-in backup-method string."""
    return type(value) is str and value in _BACKUP_METHODS


def _bounded_nonnegative_integer(value: object) -> bool:
    """Return whether a value is an exact integer in PostgreSQL bigint range."""
    return type(value) is int and 0 <= value <= _MAX_SIGNED_BIGINT


@dataclass(frozen=True, slots=True)
class PostgresRecoveryReceipt:
    """Represent content-free integrity metadata for one PostgreSQL backup artifact."""

    package_version: str
    source_commit: str
    postgres_major: int
    schema_sha256: str
    backup_method: str
    backup_sha256: str
    backup_size_bytes: int
    started_at_epoch: int
    completed_at_epoch: int

    def __post_init__(self) -> None:
        """Fail closed when untrusted receipt metadata violates the bounded schema."""
        valid = (
            _plain_text_matches(self.package_version, _VERSION_RE)
            and _plain_text_matches(self.source_commit, _COMMIT_RE)
            and type(self.postgres_major) is int
            and 1 <= self.postgres_major <= 99
            and _plain_text_matches(self.schema_sha256, _SHA256_RE)
            and _plain_backup_method(self.backup_method)
            and _plain_text_matches(self.backup_sha256, _SHA256_RE)
            and _bounded_nonnegative_integer(self.backup_size_bytes)
            and self.backup_size_bytes > 0
            and _bounded_nonnegative_integer(self.started_at_epoch)
            and _bounded_nonnegative_integer(self.completed_at_epoch)
            and self.completed_at_epoch >= self.started_at_epoch
        )
        if not valid:
            raise PostgresRecoveryReceiptError(
                "invalid PostgreSQL recovery receipt metadata"
            )

    def as_dict(self) -> dict[str, object]:
        """Return the stable machine-readable receipt schema."""
        return {
            "schema_version": 1,
            "package_version": self.package_version,
            "source_commit": self.source_commit,
            "postgres_major": self.postgres_major,
            "schema_sha256": self.schema_sha256,
            "backup_method": self.backup_method,
            "backup_sha256": self.backup_sha256,
            "backup_size_bytes": self.backup_size_bytes,
            "started_at_epoch": self.started_at_epoch,
            "completed_at_epoch": self.completed_at_epoch,
        }

    def to_json(self) -> str:
        """Return deterministic compact JSON without deployment or business content."""
        return json.dumps(
            self.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )


def parse_postgres_recovery_receipt(raw_receipt: str) -> PostgresRecoveryReceipt:
    """Parse one bounded receipt and reject extensions or malformed metadata."""
    if type(raw_receipt) is not str:
        raise PostgresRecoveryReceiptError("invalid PostgreSQL recovery receipt JSON")
    try:
        encoded_size = len(raw_receipt.encode("utf-8"))
    except UnicodeError:
        raise PostgresRecoveryReceiptError(
            "invalid PostgreSQL recovery receipt JSON"
        ) from None
    if encoded_size == 0 or encoded_size > _MAX_RECEIPT_JSON_BYTES:
        raise PostgresRecoveryReceiptError("invalid PostgreSQL recovery receipt JSON")
    try:
        decoded = json.loads(raw_receipt)
    except json.JSONDecodeError:
        raise PostgresRecoveryReceiptError(
            "invalid PostgreSQL recovery receipt JSON"
        ) from None
    if type(decoded) is not dict or frozenset(decoded) != _RECEIPT_KEYS:
        raise PostgresRecoveryReceiptError("invalid PostgreSQL recovery receipt schema")
    if decoded.get("schema_version") != 1 or type(decoded.get("schema_version")) is not int:
        raise PostgresRecoveryReceiptError("invalid PostgreSQL recovery receipt schema")
    return PostgresRecoveryReceipt(
        package_version=decoded["package_version"],
        source_commit=decoded["source_commit"],
        postgres_major=decoded["postgres_major"],
        schema_sha256=decoded["schema_sha256"],
        backup_method=decoded["backup_method"],
        backup_sha256=decoded["backup_sha256"],
        backup_size_bytes=decoded["backup_size_bytes"],
        started_at_epoch=decoded["started_at_epoch"],
        completed_at_epoch=decoded["completed_at_epoch"],
    )
