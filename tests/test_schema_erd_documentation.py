# SPDX-License-Identifier: Apache-2.0
"""The package ERD must name every protected-main table and the checkpoint overlay."""

from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPOSITORY_ROOT / "pg_llm_batch" / "schema.sql"
CHECKPOINT_MIGRATION = (
    REPOSITORY_ROOT
    / "pg_llm_batch"
    / "migrations"
    / "0007_result_stream_checkpoints.sql"
)
ERD = REPOSITORY_ROOT / "docs" / "erd" / "package-owned-schema.md"
FITNESS = REPOSITORY_ROOT / "docs" / "DOCUMENTATION_FITNESS.md"
_TABLE_NAME = re.compile(
    r"CREATE TABLE IF NOT EXISTS ([a-z][a-z0-9_]+)",
    re.MULTILINE,
)


def _read(path: Path) -> str:
    """Return one repository text file as UTF-8."""
    return path.read_text(encoding="utf-8")


def _table_names(sql_text: str) -> tuple[str, ...]:
    """Return CREATE TABLE names in document order."""
    return tuple(_TABLE_NAME.findall(sql_text))


def test_erd_names_every_packaged_schema_table() -> None:
    """An acquisition reviewer can map SQL objects without reading schema.sql first."""
    erd = _read(ERD)
    tables = _table_names(_read(SCHEMA))
    assert tables, "packaged schema must declare tables"
    for table_name in tables:
        assert table_name in erd, table_name
        assert "_" in table_name


def test_erd_labels_checkpoint_table_as_migration_owned() -> None:
    """Checkpoint storage is packaged by migration 0007, not the init schema copy."""
    erd = _read(ERD)
    checkpoint_tables = _table_names(_read(CHECKPOINT_MIGRATION))
    assert checkpoint_tables == ("llm_result_stream_checkpoints",)
    assert "llm_result_stream_checkpoints" in erd
    assert "0007" in erd
    assert "ACTIVE-PR" in erd or "not a distributed exactly-once" in erd.lower()


def test_erd_uses_tenant_qualified_identities() -> None:
    """The diagram must show the tenant-qualified lifecycle and checkpoint keys."""
    erd = _read(ERD)
    assert "tenant_scope, endpoint_alias, remote_batch_id" in erd
    assert "checkpoint_consumer_name" in erd
    assert "erDiagram" in erd


def test_fitness_inventory_tracks_the_erd_overlay() -> None:
    """The fitness matrix must stop calling the ERD merely planned."""
    fitness = _read(FITNESS)
    assert "docs/erd/package-owned-schema.md" in fitness
    assert "| ERD / schema model | PLANNED |" not in fitness
