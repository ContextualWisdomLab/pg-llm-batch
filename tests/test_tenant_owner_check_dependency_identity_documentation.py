# SPDX-License-Identifier: Apache-2.0
"""Contract tests for lifecycle-outbox CHECK dependency identity authority."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("owner_path", ("AGENTS.md", "CLAUDE.md"))
def test_owner_instructions_preserve_check_dependency_identity_boundary(
    owner_path: str,
) -> None:
    """Owner instructions must retain CHECK object identity beyond deparse equality."""
    text = Path(owner_path).read_text(encoding="utf-8")

    assert "CHECK dependency identity" in text
    assert "pg_catalog.pg_depend" in text
    assert "normal dependency" in text
    assert "before tenant binding" in text


def test_check_semantics_adr_records_dependency_identity_boundary() -> None:
    """ADR 0026 must retain the same-deparse dependency-identity decision."""
    text = Path("docs/adr/0026-lifecycle-outbox-check-semantics-authority.md").read_text(
        encoding="utf-8"
    )

    assert "Status: Proposed" in text
    assert "same-deparse" in text
    assert "pg_catalog.pg_depend" in text
    assert "DEPENDENCY_NORMAL" in text
    assert "search_path" in text
