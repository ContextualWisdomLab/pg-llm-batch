# SPDX-License-Identifier: Apache-2.0
"""Canonical documentation contract for retiring legacy database extensions."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = ROOT / "docs/adr/legacy-postgresql-extension-retirement.md"
INDEX_PATH = ROOT / "docs/adr/README.md"
ARCHITECTURE_PATH = ROOT / "ARCHITECTURE.md"


def test_legacy_extension_retirement_is_planned_and_dependency_bound() -> None:
    """Bind Issue #103 to the post-#101 upgrade-migration safety contract."""
    adr = ADR_PATH.read_text(encoding="utf-8")
    index = INDEX_PATH.read_text(encoding="utf-8")
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    lowered = adr.lower()

    assert "](legacy-postgresql-extension-retirement.md)" in index
    assert "Issue #103" in adr
    assert "PLANNED" in adr
    assert "protected-main result" in adr
    assert "#101" in adr
    assert "pg_cron" in adr
    assert "pgsql-http" in adr
    assert "shared_preload_libraries" in adr
    assert "gateway_retrieval_logs" in adr
    assert "DROP EXTENSION ... CASCADE" in adr
    assert "fail closed" in lowered
    assert "#102" in adr
    assert "independent" in lowered
    assert "no new persistence" in lowered
    assert "clean fresh database" in lowered
    assert "upgraded legacy" in lowered
    assert "SBOM/provenance" in adr
    assert "Release Acceptance" in adr

    assert "RetireExtensions" in architecture
    assert "Issue #103" in architecture
    assert "legacy-postgresql-extension-retirement.md" in architecture
