# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for runtime-store write privilege readiness."""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from pg_llm_batch import config as config_mod
from pg_llm_batch.exceptions import ConfigError


_CONFIG_TYPES = {
    "config_key": "text",
    "config_value": "text",
    "config_description": "text",
    "updated_at": "timestamp with time zone",
}


class _PrivilegeProbeCursor:
    """Return a compatible table while retaining the catalog SQL for inspection."""

    def __init__(self, statements: list[str]) -> None:
        self._statements = statements
        self._result: list[tuple[Any, ...]] = []

    def __enter__(self) -> "_PrivilegeProbeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Return compatible catalog evidence for the query under test."""
        normalized = " ".join(sql.lower().split())
        self._statements.append(normalized)
        if "pg_catalog.pg_index" in normalized:
            self._result = [(True,)]
            return
        requested_columns = tuple((params or (None, ()))[1])
        self._result = [
            ("r", column_name, _CONFIG_TYPES[column_name], True, True)
            for column_name in requested_columns
        ]

    def fetchone(self) -> tuple[Any, ...] | None:
        """Return the first prepared result row."""
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Return all prepared result rows."""
        return list(self._result)


class _PrivilegeProbeConnection:
    """Expose a compatible catalog response and captured SQL statements."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def cursor(self) -> _PrivilegeProbeCursor:
        return _PrivilegeProbeCursor(self.statements)


def test_schema_readiness_requires_select_insert_and_update_privileges() -> None:
    """A write-capable store must probe every DML privilege used by its upsert."""
    connection = _PrivilegeProbeConnection()

    assert config_mod._schema_is_compatible(
        connection,
        "com_config",
        _CONFIG_TYPES,
        "config_key",
    )

    catalog_sql = next(
        statement
        for statement in connection.statements
        if "has_table_privilege" in statement
    )
    assert "'select'" in catalog_sql
    assert "'insert'" in catalog_sql
    assert "'update'" in catalog_sql


DSN = os.environ.get("PG_LLM_BATCH_TEST_DSN")
skip_no_db = pytest.mark.skipif(
    not DSN, reason="PG_LLM_BATCH_TEST_DSN not set; skipping live-DB integration"
)


@pytest.mark.integration
@skip_no_db
@pytest.mark.parametrize("missing_privilege", ["INSERT", "UPDATE"])
def test_live_config_store_rejects_roles_missing_required_write_privilege(
    missing_privilege: str,
) -> None:
    """Real PostgreSQL roles missing either upsert privilege must fail at readiness."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    suffix = uuid.uuid4().hex[:12]
    role_name = f"config_priv_test_{suffix}"
    password = uuid.uuid4().hex
    retained_write_privilege = "UPDATE" if missing_privilege == "INSERT" else "INSERT"
    role_dsn = make_conninfo(DSN, user=role_name, password=password)

    with psycopg.connect(DSN) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                    "NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role_name), sql.Literal(password))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(role_name)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, {} ON com_config TO {}").format(
                    sql.SQL(retained_write_privilege),
                    sql.Identifier(role_name),
                )
            )
        admin.commit()

    try:
        with pytest.raises(ConfigError) as caught:
            config_mod.PostgresConfigStore(role_dsn)
        assert caught.value.message == "Configuration schema is unavailable or incompatible"
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
    finally:
        with psycopg.connect(DSN) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
                )
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
            admin.commit()