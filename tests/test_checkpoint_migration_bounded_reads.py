# SPDX-License-Identifier: Apache-2.0
"""Security regression for bounded checkpoint migration file reads."""

from __future__ import annotations

from pg_llm_batch import checkpoint_migrations


class _BoundedMigrationFile:
    """Record the maximum byte request used by one package migration read."""

    def __init__(self, payload: bytes, read_sizes: list[int]) -> None:
        self.payload = payload
        self.read_sizes = read_sizes

    def __enter__(self) -> _BoundedMigrationFile:
        """Return this deterministic file double."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Leave cleanup to the in-memory test double."""
        return None

    def read(self, size: int = -1) -> bytes:
        """Reject unbounded reads and return the configured SQL bytes."""
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError("migration SQL read must be bounded")
        return self.payload[:size]


class _BoundedMigrationPath:
    """Expose only an explicitly sized binary read for one fake path."""

    def __init__(self, payload: bytes, read_sizes: list[int]) -> None:
        self.payload = payload
        self.read_sizes = read_sizes

    def open(self, mode: str) -> _BoundedMigrationFile:
        """Require binary read mode and return the bounded file double."""
        assert mode == "rb"
        return _BoundedMigrationFile(self.payload, self.read_sizes)

    def read_bytes(self) -> bytes:
        """Fail if production falls back to Path.read_bytes()."""
        raise AssertionError("Path.read_bytes() is an unbounded migration read")


def test_plan_reads_at_most_one_byte_beyond_the_migration_limit(monkeypatch) -> None:
    """Canonical SQL planning never materializes an arbitrarily large file."""
    read_sizes: list[int] = []
    monkeypatch.setattr(
        checkpoint_migrations,
        "_CHECKPOINT_SCHEMA_MIGRATION_PATHS",
        (
            (
                "0007_result_stream_checkpoints",
                _BoundedMigrationPath(b"SELECT 1;", read_sizes),
            ),
            (
                "0008_result_checkpoint_audit_events",
                _BoundedMigrationPath(b"SELECT 2;", read_sizes),
            ),
        ),
    )

    plan = checkpoint_migrations.plan_checkpoint_schema_migrations()

    assert len(plan) == 2
    assert read_sizes == [
        checkpoint_migrations.MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES + 1,
        checkpoint_migrations.MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES + 1,
    ]
