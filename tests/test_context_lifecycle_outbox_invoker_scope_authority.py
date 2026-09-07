# SPDX-License-Identifier: Apache-2.0
"""Contracts for caller-visible SECURITY INVOKER tenant-scope authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class CapturingCursor:
    """Capture the runtime-admission SQL without emulating PostgreSQL catalogs."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record normalized admission SQL for structural assertions."""
        assert params is None
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool]:
        """Return the safe catalog verdict used by this static contract."""
        return (False, False)


def _read_repository_text(relative_path: str) -> str:
    """Read one repository-owned contract document as UTF-8 text."""
    return (_REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_runtime_scans_callable_security_invoker_tenant_scope_proconfig() -> None:
    """Invoker-local tenant GUC authority must be inspected on the caller principal."""
    cursor = CapturingCursor()

    _require_rls_application_role(cursor)

    assert "executable_invoker_scope_override" in cursor.sql
    assert "NOT executable_invoker_scope_override.prosecdef" in cursor.sql
    assert "invoker_scope_schema" in cursor.sql
    assert "pg_catalog.has_schema_privilege(selectable_role.oid" in cursor.sql
    assert (
        "pg_catalog.has_function_privilege(selectable_role.oid, "
        "executable_invoker_scope_override.oid, 'EXECUTE')"
    ) in cursor.sql
    assert "invoker_scope_setting.setting" in cursor.sql
    assert (
        "pg_catalog.split_part(invoker_scope_setting.setting, '=', 1) "
        "OPERATOR(pg_catalog.=) 'pg_llm_batch.tenant_scope'"
    ) in cursor.sql


def test_agents_retains_security_invoker_tenant_scope_boundary() -> None:
    """Repository owner instructions must retain the direct invoker authority route."""
    agents = _read_repository_text("AGENTS.md")

    assert "SECURITY INVOKER" in agents
    assert "pg_llm_batch.tenant_scope" in agents
    assert "before tenant binding" in agents


def test_claude_retains_security_invoker_tenant_scope_boundary() -> None:
    """Implementation instructions must retain the direct invoker authority route."""
    claude = _read_repository_text("CLAUDE.md")

    assert "SECURITY INVOKER" in claude
    assert "pg_llm_batch.tenant_scope" in claude
    assert "before tenant binding" in claude


def test_adr_0032_distinguishes_invoker_and_definer_authority() -> None:
    """The Proposed ADR must record why invoker and definer routines use different principals."""
    adr = _read_repository_text(
        "docs/adr/0032-lifecycle-outbox-dml-grant-option-authority.md"
    )

    assert "Status: Proposed" in adr
    assert "SECURITY INVOKER" in adr
    assert "pg_llm_batch.tenant_scope" in adr
    assert "proconfig" in adr
    assert "selectable principal" in adr
    assert "SECURITY DEFINER" in adr
