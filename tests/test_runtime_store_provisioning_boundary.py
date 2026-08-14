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
