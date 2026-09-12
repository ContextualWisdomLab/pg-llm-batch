# SPDX-License-Identifier: Apache-2.0
"""Documentation contracts for legacy PostgreSQL extension retirement."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPERABILITY = ROOT / "docs" / "OPERABILITY.md"
ADR = ROOT / "docs" / "adr" / "0031-legacy-postgresql-extension-retirement.md"
DOCTORING = ROOT / "docs" / "doctoring" / "legacy-postgresql-extension-retirement.md"
MIGRATION = ROOT / "docker" / "postgres" / "migrations" / "retire_legacy_provider_extensions.sql"


def _text(path: Path) -> str:
    """Read one bounded owner document as UTF-8."""
    return path.read_text(encoding="utf-8")


def test_operator_guide_documents_safe_execution_and_recovery() -> None:
    """Operators need preflight, bounded failure recovery, replay, and rollback."""
    text = _text(OPERABILITY)

    for required in (
        "03_cron_batch_retrieval.sql",
        "to_regclass('cron.job')",
        "\\gset",
        "\\if :cron_job_available",
        "pg_catalog.pg_depend",
        "dep.deptype = 'x'",
        "lock_timeout = '5s'",
        "DROP EXTENSION IF EXISTS http RESTRICT",
        "DROP EXTENSION IF EXISTS pg_cron RESTRICT",
        "gateway_retrieval_logs",
        "Fail-closed recovery",
        "idempotent",
        "Rollback boundary",
    ):
        assert required in text
    assert "Do not replace `RESTRICT` with `CASCADE`" in text
    assert "Unexpected extension member remains" in text
    assert "Explicit `DEPENDS ON EXTENSION` object remains" in text


def test_adr_and_doctoring_preserve_the_authority_boundary() -> None:
    """The bounded owner docs must separate DB cleanup from provider authority."""
    adr = _text(ADR)
    doctoring = _text(DOCTORING)

    assert adr.startswith(
        "# ADR 0031: Fail-closed retirement of legacy PostgreSQL provider extensions\n"
    )
    assert "Status:** Proposed" in adr
    assert "direct provider-network" in adr
    assert "shared_preload_libraries" in adr
    assert "deptype = 'x'" in adr
    assert "deptype = 'e'" in adr
    assert "Never use `CASCADE`" in adr
    assert "operator-owned functions or dependencies" in adr

    assert "pg_depend" in doctoring
    assert "DEPENDS ON EXTENSION" in doctoring
    assert "PostgreSQL Global Development Group. (2026)." in doctoring
    assert "Unsupported claims" in doctoring


def test_migration_and_owner_docs_expose_the_same_fail_closed_action() -> None:
    """Executable migration and bounded docs must agree without owning root docs."""
    migration = _text(MIGRATION)
    operability = _text(OPERABILITY)
    doctoring = _text(DOCTORING)

    for token in (
        "SET LOCAL lock_timeout = '5s'",
        "DROP EXTENSION IF EXISTS http RESTRICT",
        "DROP EXTENSION IF EXISTS pg_cron RESTRICT",
    ):
        assert token in migration
        assert token in operability

    assert "CASCADE" not in "\n".join(
        line for line in migration.splitlines() if not line.lstrip().startswith("--")
    )
    assert "gateway_retrieval_logs" in operability
    assert "gateway_retrieval_logs" in doctoring
