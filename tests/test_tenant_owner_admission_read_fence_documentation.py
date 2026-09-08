# SPDX-License-Identifier: Apache-2.0
"""Contract tests for lifecycle-outbox admission-to-read relation fencing."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("owner_path", ("AGENTS.md", "CLAUDE.md"))
def test_owner_instructions_preserve_admission_to_read_lock_boundary(
    owner_path: str,
) -> None:
    """Owner instructions must retain relation identity through read consumption."""
    text = Path(owner_path).read_text(encoding="utf-8")

    assert "ACCESS SHARE" in text
    assert "admission-to-read" in text
    assert "relation" in text.lower()
    assert "SELECT" in text
    assert "buyer-path" in text


def test_table_program_adr_records_admission_to_read_lock_boundary() -> None:
    """The table-program ADR must retain the verified read-side DDL-race decision."""
    text = Path("docs/adr/0024-lifecycle-outbox-table-program-authority.md").read_text(
        encoding="utf-8"
    )

    assert "ACCESS SHARE" in text
    assert "admission-to-read" in text
    assert "relation-identity TOCTOU" in text
    assert "34173601154" in text
    assert "101898554640" in text
