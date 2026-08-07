# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Atomic operator workflow for durable checkpoint and audit migrations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .checkpoint_audit import AUDIT_MIGRATION_PATH
from .checkpoint_store import MIGRATION_PATH
from .db import _require_psycopg, psycopg

MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES = 1_048_576
CHECKPOINT_SCHEMA_MIGRATION_LOCK_NAMESPACE = 1_346_849_869
CHECKPOINT_SCHEMA_MIGRATION_LOCK_OPERATION = 1_111_577_672
_CHECKPOINT_SCHEMA_MIGRATION_PATHS: tuple[tuple[str, Path], ...] = (
    ("0007_result_stream_checkpoints", MIGRATION_PATH),
    ("0008_result_checkpoint_audit_events", AUDIT_MIGRATION_PATH),
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _supported_migration_ids() -> frozenset[str]:
    """Return the exact migration identifiers configured for this invocation."""
    return frozenset(migration_id for migration_id, _path in _CHECKPOINT_SCHEMA_MIGRATION_PATHS)


@dataclass(frozen=True, slots=True)
class CheckpointSchemaMigration:
    """Describe one bounded canonical checkpoint-storage migration."""

    migration_id: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        """Reject ambiguous or unbounded public migration evidence."""
        if (
            not isinstance(self.migration_id, str)
            or self.migration_id not in _supported_migration_ids()
        ):
            raise ValueError("migration_id must identify a configured migration")
        if (
            isinstance(self.byte_count, bool)
            or not isinstance(self.byte_count, int)
            or self.byte_count < 1
            or self.byte_count > MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES
        ):
            raise ValueError(
                "byte_count must be an integer from 1 through "
                f"{MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES}"
            )
        if (
            not isinstance(self.sha256, str)
            or _SHA256_PATTERN.fullmatch(self.sha256) is None
        ):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest")

    def as_dict(self) -> dict[str, int | str]:
        """Return one stable JSON-compatible migration evidence object."""
        return {
            "migration_id": self.migration_id,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class _LoadedCheckpointSchemaMigration:
    """Keep reviewed SQL private while carrying its public descriptor."""

    descriptor: CheckpointSchemaMigration
    sql: str


def _load_checkpoint_schema_migration(
    migration_id: str,
    migration_path: Path,
) -> _LoadedCheckpointSchemaMigration:
    """Load, bound, decode, and identify one migration before database access."""
    sql_bytes = migration_path.read_bytes()
    byte_count = len(sql_bytes)
    if byte_count < 1 or byte_count > MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES:
        raise RuntimeError("checkpoint schema migration has an invalid bounded size")
    sql = sql_bytes.decode("utf-8", errors="strict")
    descriptor = CheckpointSchemaMigration(
        migration_id=migration_id,
        byte_count=byte_count,
        sha256=hashlib.sha256(sql_bytes).hexdigest(),
    )
    return _LoadedCheckpointSchemaMigration(descriptor=descriptor, sql=sql)


def _load_checkpoint_schema_migrations() -> tuple[_LoadedCheckpointSchemaMigration, ...]:
    """Load every configured migration in canonical order before database access."""
    return tuple(
        _load_checkpoint_schema_migration(migration_id, migration_path)
        for migration_id, migration_path in _CHECKPOINT_SCHEMA_MIGRATION_PATHS
    )


def plan_checkpoint_schema_migrations() -> tuple[CheckpointSchemaMigration, ...]:
    """Return bounded identity evidence for the canonical migration plan."""
    return tuple(
        migration.descriptor for migration in _load_checkpoint_schema_migrations()
    )


def apply_checkpoint_schema_migrations(
    postgres_dsn: str,
) -> tuple[CheckpointSchemaMigration, ...]:
    """Apply checkpoint and audit schema atomically in canonical order.

    Both canonical files are loaded and validated before psycopg or database
    access. One package-owned transaction obtains a fixed transaction-level
    advisory lock, executes the durable checkpoint migration before the audit
    migration, and commits once. Any exception leaves the connection context
    before that commit, allowing PostgreSQL to roll the transaction back and
    release the advisory lock.
    """
    loaded = _load_checkpoint_schema_migrations()
    _require_psycopg()
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (
                    CHECKPOINT_SCHEMA_MIGRATION_LOCK_NAMESPACE,
                    CHECKPOINT_SCHEMA_MIGRATION_LOCK_OPERATION,
                ),
            )
            for migration in loaded:
                cursor.execute(migration.sql)
        connection.commit()
    return tuple(migration.descriptor for migration in loaded)
