# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for runtime-store unique-index key semantics."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import config as config_mod
from pg_llm_batch.exceptions import ConfigError

_CONFIG_TYPES = {
    "config_description": "text",
    "config_key": "text",
    "config_value": "text",
    "updated_at": "timestamp with time zone",
}
_SECRET_TYPES = {
    "is_encrypted": "boolean",
    "secret_key": "text",
    "secret_value": "text",
    "updated_at": "timestamp with time zone",
}


class _IncludeOnlyCursor:
    """Model a UNIQUE(other_key) INCLUDE(storage_key) catalog shape."""

    def __init__(self, column_types: dict[str, str]) -> None:
        self._column_types = column_types
        self._result: list[tuple[Any, ...]] = []

    def __enter__(self) -> "_IncludeOnlyCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Return the catalog result PostgreSQL would expose for each probe shape."""
        normalized = " ".join(sql.lower().split())
        self._result = []
        if "pg_catalog.pg_index" in normalized:
            if (
                "with ordinality" in normalized
                and "ordinal_position <= idx.indnkeyatts" in normalized
            ):
                # The storage key is present only after the unique key columns,
                # so it is an INCLUDE payload column and cannot arbitrate
                # ON CONFLICT(storage_key).
                self._result = [(False,)]
                return
            if "key_attr.attnum = any(idx.indkey::smallint[])" in normalized:
                # This is the buggy broad-membership probe: pg_index.indkey
                # contains both key and INCLUDE columns, so it falsely accepts
                # the storage key even though it is not itself unique.
                self._result = [(True,)]
                return
            raise AssertionError("unique-index probe must inspect key columns only")

        if "from pg_catalog.pg_class" in normalized:
            requested_columns = tuple((params or (None, ()))[1])
            self._result = [
                (
                    "r",
                    column_name,
                    self._column_types[column_name],
                    True,
                    True,
                )
                for column_name in requested_columns
            ]

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._result[0] if self._result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._result)


class _IncludeOnlyConnection:
    """Connection exposing an otherwise compatible table with include-only key evidence."""

    def __init__(self, column_types: dict[str, str]) -> None:
        self.autocommit = False
        self.closed = False
        self._column_types = column_types

    def cursor(self) -> _IncludeOnlyCursor:
        return _IncludeOnlyCursor(self._column_types)

    def close(self) -> None:
        self.closed = True


class _IncludeOnlyPsycopg:
    """Return one controlled connection for runtime-store construction."""

    def __init__(self, column_types: dict[str, str]) -> None:
        self.connection = _IncludeOnlyConnection(column_types)

    def connect(self, _dsn: str) -> _IncludeOnlyConnection:
        return self.connection


class _DeferrableConstraintCursor(_IncludeOnlyCursor):
    """Model a unique key backed only by a DEFERRABLE unique constraint."""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Reject only probes that prove a deferrable constraint is not an arbiter."""
        normalized = " ".join(sql.lower().split())
        if "pg_catalog.pg_index" in normalized:
            self._result = [
                (
                    False
                    if "pg_catalog.pg_constraint" in normalized
                    and "condeferrable" in normalized
                    else True,
                )
            ]
            return
        super().execute(sql, params)


class _DeferrableConstraintConnection(_IncludeOnlyConnection):
    """Expose a type-correct table whose storage key uniqueness is deferrable."""

    def cursor(self) -> _DeferrableConstraintCursor:
        return _DeferrableConstraintCursor(self._column_types)


class _DeferrableConstraintPsycopg:
    """Return one connection with a DEFERRABLE unique storage-key constraint."""

    def __init__(self, column_types: dict[str, str]) -> None:
        self.connection = _DeferrableConstraintConnection(column_types)

    def connect(self, _dsn: str) -> _DeferrableConstraintConnection:
        return self.connection


@pytest.mark.parametrize("store_kind", ["config", "secret"])
def test_runtime_store_rejects_storage_key_that_is_only_an_included_column(
    monkeypatch: pytest.MonkeyPatch,
    store_kind: str,
) -> None:
    """INCLUDE payload membership must not masquerade as unique-key authority."""
    column_types = _CONFIG_TYPES if store_kind == "config" else _SECRET_TYPES
    fake = _IncludeOnlyPsycopg(column_types)
    monkeypatch.setattr(config_mod, "psycopg", fake)

    expected_message = (
        "Configuration schema is unavailable or incompatible"
        if store_kind == "config"
        else "Secret schema is unavailable or incompatible"
    )
    with pytest.raises(ConfigError) as caught:
        if store_kind == "config":
            config_mod.PostgresConfigStore("postgresql://runtime")
        else:
            config_mod.SecretStore(
                "postgresql://runtime", require_encryption=False
            )

    assert caught.value.message == expected_message
    assert caught.value.error_code == "CONFIG_ERROR"
    assert fake.connection.closed is True
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("store_kind", ["config", "secret"])
def test_runtime_store_rejects_deferrable_unique_storage_key_constraint(
    monkeypatch: pytest.MonkeyPatch,
    store_kind: str,
) -> None:
    """DEFERRABLE uniqueness must not be accepted as ON CONFLICT arbiter authority."""
    column_types = _CONFIG_TYPES if store_kind == "config" else _SECRET_TYPES
    fake = _DeferrableConstraintPsycopg(column_types)
    monkeypatch.setattr(config_mod, "psycopg", fake)

    expected_message = (
        "Configuration schema is unavailable or incompatible"
        if store_kind == "config"
        else "Secret schema is unavailable or incompatible"
    )
    with pytest.raises(ConfigError) as caught:
        if store_kind == "config":
            config_mod.PostgresConfigStore("postgresql://runtime")
        else:
            config_mod.SecretStore(
                "postgresql://runtime", require_encryption=False
            )

    assert caught.value.message == expected_message
    assert caught.value.error_code == "CONFIG_ERROR"
    assert fake.connection.closed is True
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
