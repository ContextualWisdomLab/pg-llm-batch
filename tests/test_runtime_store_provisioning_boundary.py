# SPDX-License-Identifier: Apache-2.0
"""Regression tests for runtime config/secret provisioning authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pg_llm_batch import config as config_mod
from pg_llm_batch.exceptions import ConfigError
from tests.conftest import FakePsycopg


def _record_sql(fake: FakePsycopg) -> list[str]:
    """Record normalized SQL handled by the shared fake without changing behavior."""
    statements: list[str] = []
    original = fake.store.handle

    def handle(sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        statements.append(sql)
        return original(sql, params)

    fake.store.handle = handle  # type: ignore[method-assign]
    return statements


def test_runtime_store_construction_does_not_provision_schema_or_seed_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary runtime construction must not require schema CREATE/seed authority."""
    fake = FakePsycopg()
    statements = _record_sql(fake)
    monkeypatch.setattr(config_mod, "psycopg", fake)

    config_store = config_mod.PostgresConfigStore("postgresql://runtime")
    secret_store = config_mod.SecretStore("postgresql://runtime")

    normalized = [statement.lower() for statement in statements]
    assert not any("create table" in statement for statement in normalized)
    assert not any(
        "insert into com_config" in statement and "do nothing" in statement
        for statement in normalized
    )

    config_store.close()
    secret_store.close()


class _FailingCursor:
    """Cursor that exposes a sensitive lower-layer diagnostic if not bounded."""

    def __enter__(self) -> "_FailingCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, _sql: str, _params: tuple[Any, ...] | None = None) -> None:
        raise RuntimeError("SECRET-SENTINEL database diagnostic")

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _FailingConnection:
    """Minimal acquired connection for constructor failure/cleanup evidence."""

    def __init__(self) -> None:
        self.autocommit = False
        self.closed = False

    def cursor(self) -> _FailingCursor:
        return _FailingCursor()

    def close(self) -> None:
        self.closed = True


class _FailingPsycopg:
    """Return one connection whose first schema/readiness statement fails."""

    def __init__(self) -> None:
        self.connection = _FailingConnection()

    def connect(self, _dsn: str) -> _FailingConnection:
        return self.connection


@pytest.mark.parametrize("store_kind", ["config", "secret"])
def test_missing_or_incompatible_runtime_schema_fails_with_bounded_package_error(
    monkeypatch: pytest.MonkeyPatch,
    store_kind: str,
) -> None:
    """Schema/readiness failure must not expose arbitrary database diagnostics."""
    fake = _FailingPsycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake)

    with pytest.raises(ConfigError) as caught:
        if store_kind == "config":
            config_mod.PostgresConfigStore("postgresql://runtime")
        else:
            config_mod.SecretStore("postgresql://runtime")

    rendered = str(caught.value)
    assert "SECRET-SENTINEL" not in rendered
    assert "schema" in rendered.lower()
    assert fake.connection.closed is True
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


class _SchemaShapeCursor:
    """Cursor that makes a relation selectable while exposing catalog shape metadata."""

    def __init__(self, relation_kind: str, column_types: dict[str, str]) -> None:
        self._relation_kind = relation_kind
        self._column_types = column_types
        self._result: list[tuple[Any, ...]] = []

    def __enter__(self) -> "_SchemaShapeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Allow ordinary SELECT and return modeled rows for pg_catalog probes."""
        normalized = " ".join(sql.lower().split())
        self._result = []
        if "from pg_catalog.pg_class" not in normalized:
            return
        requested_columns = tuple((params or (None, ()))[1])
        self._result = [
            (self._relation_kind, column_name, self._column_types[column_name])
            for column_name in requested_columns
            if column_name in self._column_types
        ]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._result)


class _SchemaShapeConnection:
    """Connection exposing a selectable relation with a controlled catalog shape."""

    def __init__(self, relation_kind: str, column_types: dict[str, str]) -> None:
        self.autocommit = False
        self.closed = False
        self._relation_kind = relation_kind
        self._column_types = column_types

    def cursor(self) -> _SchemaShapeCursor:
        return _SchemaShapeCursor(self._relation_kind, self._column_types)

    def close(self) -> None:
        self.closed = True


class _SchemaShapePsycopg:
    """Return a single connection with controlled relation/catalog metadata."""

    def __init__(self, relation_kind: str, column_types: dict[str, str]) -> None:
        self.connection = _SchemaShapeConnection(relation_kind, column_types)

    def connect(self, _dsn: str) -> _SchemaShapeConnection:
        return self.connection


_CONFIG_TYPES = {
    "config_key": "text",
    "config_value": "text",
    "config_description": "text",
    "updated_at": "timestamp with time zone",
}
_SECRET_TYPES = {
    "secret_key": "text",
    "secret_value": "text",
    "is_encrypted": "boolean",
    "updated_at": "timestamp with time zone",
}


@pytest.mark.parametrize(
    ("store_kind", "relation_kind", "column_types"),
    [
        ("config", "v", _CONFIG_TYPES),
        ("config", "r", {**_CONFIG_TYPES, "config_value": "integer"}),
        ("secret", "v", _SECRET_TYPES),
        ("secret", "r", {**_SECRET_TYPES, "is_encrypted": "text"}),
    ],
)
def test_runtime_store_rejects_selectable_view_or_wrong_column_type(
    monkeypatch: pytest.MonkeyPatch,
    store_kind: str,
    relation_kind: str,
    column_types: dict[str, str],
) -> None:
    """Selectable views and wrong column types must fail closed and clean up."""
    fake = _SchemaShapePsycopg(relation_kind, column_types)
    monkeypatch.setattr(config_mod, "psycopg", fake)

    expected_message = (
        "Configuration schema is unavailable or incompatible"
        if store_kind == "config"
        else "Secret schema is unavailable or incompatible"
    )
    with pytest.raises(ConfigError, match=f"^{expected_message}$") as caught:
        if store_kind == "config":
            config_mod.PostgresConfigStore("postgresql://runtime")
        else:
            config_mod.SecretStore("postgresql://runtime")

    assert fake.connection.closed is True
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_provisioned_schema_owns_default_seeding_and_docker_mirror() -> None:
    """Fresh provisioning must seed built-ins outside runtime constructors."""
    package_schema = Path("pg_llm_batch/schema.sql").read_text(encoding="utf-8")
    docker_schema = Path("docker/postgres/init/02_schema.sql").read_text(encoding="utf-8")

    assert package_schema == docker_schema
    lowered = package_schema.lower()
    assert "insert into com_config" in lowered
    assert "on conflict (config_key) do nothing" in lowered
    for full_key in sorted(config_mod.DEFAULT_CONFIG_INDEX):
        assert full_key in package_schema
