# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for retiring legacy database extensions."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, heading: str, next_heading_prefix: str) -> str:
    """Return one Markdown section beginning at an exact heading."""
    start = text.index(heading)
    tail = text[start + len(heading) :]
    next_offset = tail.find(next_heading_prefix)
    return text[start:] if next_offset < 0 else text[start : start + len(heading) + next_offset]


def test_legacy_extension_retirement_is_planned_and_dependency_bound() -> None:
    """Bind Issue #103 to the post-#101 upgrade-migration safety contract."""
    prd = (ROOT / "docs/product/PRD.md").read_text(encoding="utf-8")
    trd = (ROOT / "docs/product/TRD.md").read_text(encoding="utf-8")
    traceability = (ROOT / "docs/TRACEABILITY.md").read_text(encoding="utf-8")
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")

    for document in (prd, trd, traceability, architecture):
        assert "#103" in document

    prd_target = _section(prd, "### PRD-T17", "\n### PRD-T")
    assert "PLANNED" in prd_target
    assert "#101" in prd_target
    assert "pg_cron" in prd_target
    assert "pgsql-http" in prd_target
    assert "DROP" in prd_target
    assert "CASCADE" in prd_target

    trd_target = _section(trd, "### TRD-R5", "\n## 9.")
    assert "PLANNED" in trd_target
    assert "#101" in trd_target
    assert "shared_preload_libraries" in trd_target
    assert "existing-volume" in trd_target

    assert "Legacy PostgreSQL extension retirement" in traceability
    assert "PLANNED #103" in traceability
    assert "RetireExtensions" in architecture
