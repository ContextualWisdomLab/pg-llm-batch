# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox row-admission authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox
from pg_llm_batch.context_lifecycle_outbox import apply_context_lifecycle_outbox_schema


class _Cursor:
    """Capture migration SQL executed by the package installer."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.calls.append(sql)


class _Connection:
    """Expose one cursor and record package-owned commits."""

    def __init__(self, calls: list[str], commits: list[int]) -> None:
        self.calls = calls
        self.commits = commits

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.calls)

    def commit(self) -> None:
        self.commits.append(1)


class _Psycopg:
    """Route the installer into deterministic in-memory evidence."""

    def __init__(self, calls: list[str], commits: list[int]) -> None:
        self.calls = calls
        self.commits = commits
        self.dsns: list[str] = []

    def connect(self, dsn: str) -> _Connection:
        self.dsns.append(dsn)
        return _Connection(self.calls, self.commits)


def test_row_admission_authority_migration_is_mirrored_and_fail_closed() -> None:
    """Unknown or semantically drifted admission objects must fail closed."""
    package_path = lifecycle_outbox._ROW_ADMISSION_AUTHORITY_MIGRATION_PATH
    docker_path = (
        Path(__file__).parents[1]
        / "docker"
        / "postgres"
        / "init"
        / "05_context_lifecycle_outbox_row_admission_authority.sql"
    )
    package_sql = Path(package_path).read_text(encoding="utf-8")
    docker_sql = docker_path.read_text(encoding="utf-8")

    assert package_sql == docker_sql
    assert "canonical_payload_check_expression TEXT" in package_sql
    assert "canonical_valid_time_check_expression TEXT" in package_sql
    assert "canonical_system_time_check_expression TEXT" in package_sql
    assert "CREATE TEMPORARY TABLE pg_llm_batch_outbox_admission_probe_v1" in package_sql
    assert "pg_catalog.pg_get_expr(conbin, conrelid, false)" in package_sql
    assert "ck_llm_context_lifecycle_outbox_payload_canonical_v1" in package_sql
    assert ") OPERATOR(pg_catalog.=) canonical_payload_check_expression" in package_sql
    assert "ck_llm_context_lifecycle_outbox_valid_time_canonical_v1" in package_sql
    assert ") OPERATOR(pg_catalog.=) canonical_valid_time_check_expression" in package_sql
    assert "ck_llm_context_lifecycle_outbox_system_time_canonical_v1" in package_sql
    assert ") OPERATOR(pg_catalog.=) canonical_system_time_check_expression" in package_sql
    assert "FROM pg_catalog.pg_trigger AS outbox_trigger" in package_sql
    assert "NOT outbox_trigger.tgisinternal" in package_sql
    assert "FROM pg_catalog.pg_rewrite AS outbox_rule" in package_sql
    assert "outbox_rule.ev_class =" in package_sql
    assert "JOIN pg_catalog.pg_attrdef AS admission_default" in package_sql
    assert "admission_attribute.attname OPERATOR(pg_catalog.=) 'context_outbox_uuid'" in package_sql
    assert "'gen_random_uuid()'" in package_sql
    assert "admission_attribute.attname OPERATOR(pg_catalog.=) 'created_at'" in package_sql
    assert "'now()'" in package_sql
    assert "FROM pg_catalog.pg_constraint AS outbox_constraint" in package_sql
    assert "outbox_constraint.contype IN ('c', 'f', 'p', 'u', 'x')" in package_sql
    assert "FROM pg_catalog.pg_class AS outbox_relation" in package_sql
    assert "outbox_relation.relrowsecurity" in package_sql
    assert "outbox_relation.relforcerowsecurity" in package_sql
    assert "FROM pg_catalog.pg_policy AS outbox_policy" in package_sql
    assert "outbox_policy.polcmd OPERATOR(pg_catalog.=) '*'" in package_sql
    assert "outbox_policy.polpermissive" in package_sql
    assert "outbox_policy.polroles OPERATOR(pg_catalog.=) ARRAY[0::pg_catalog.oid]" in package_sql
    assert "pg_catalog.pg_get_expr(outbox_policy.polqual" in package_sql
    assert "pg_catalog.pg_get_expr(outbox_policy.polwithcheck" in package_sql
    assert "FROM pg_catalog.pg_index AS admission_index" in package_sql
    assert "admission_index.indisunique" in package_sql
    assert "admission_index.indexprs IS NOT NULL" in package_sql
    assert "admission_index.indpred IS NOT NULL" in package_sql
    assert "JOIN pg_catalog.pg_class AS admission_index_relation" in package_sql
    assert "FROM pg_catalog.pg_opclass AS admission_opclass" in package_sql
    assert "JOIN pg_catalog.pg_attribute AS actual_attribute" in package_sql
    assert "admission_opclass.opcmethod = admission_index_relation.relam" in package_sql
    assert "admission_opclass.opcnamespace =" in package_sql
    assert "'pg_catalog'::pg_catalog.regnamespace" in package_sql
    assert "admission_opclass.opcdefault" in package_sql
    assert "admission_opclass.opcintype = actual_attribute.atttypid" in package_sql
    assert "unexpected lifecycle outbox row-admission authority" in package_sql


def test_default_schema_install_applies_base_and_authority_migrations_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The package default must run 0008 then 0009 before its single commit."""
    calls: list[str] = []
    commits: list[int] = []
    fake = _Psycopg(calls, commits)
    monkeypatch.setattr(lifecycle_outbox, "_require_psycopg", lambda: None)
    monkeypatch.setattr(lifecycle_outbox, "psycopg", fake)

    apply_context_lifecycle_outbox_schema("postgresql://unit")

    assert fake.dsns == ["postgresql://unit"]
    assert len(calls) == 2
    assert "CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox" in calls[0]
    assert "unexpected lifecycle outbox row-admission authority" in calls[1]
    assert commits == [1]
