# SPDX-License-Identifier: Apache-2.0
"""Contract tests for lifecycle-outbox admission-to-write DDL fencing."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("owner_path", ("AGENTS.md", "CLAUDE.md"))
def test_owner_instructions_preserve_admission_to_write_lock_boundary(
    owner_path: str,
) -> None:
    """Owner instructions must retain the write-schema fence around live admission."""
    text = Path(owner_path).read_text(encoding="utf-8")

    assert "ROW EXCLUSIVE" in text
    assert "admission" in text.lower()
    assert "INSERT" in text
    assert "CREATE TRIGGER" in text
    assert "admission-to-write" in text


def test_table_program_adr_records_admission_to_write_lock_boundary() -> None:
    """The table-program ADR must retain the verified DDL-race decision."""
    text = Path("docs/adr/0024-lifecycle-outbox-table-program-authority.md").read_text(
        encoding="utf-8"
    )

    assert "ROW EXCLUSIVE" in text
    assert "admission-to-write" in text
    assert "CREATE TRIGGER" in text
    assert "does not protect against a PostgreSQL superuser mutating catalogs" not in text
