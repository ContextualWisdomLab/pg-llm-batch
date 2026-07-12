# SPDX-License-Identifier: Apache-2.0
"""Shared test fakes.

We fake the tiny subset of psycopg the unit tests exercise, so the KV stores
and the pg_tiktoken SQL wrapper can be tested without a live database. The
integration test (``-m integration``) uses a real container instead.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class FakeCursor:
    """A cursor over a shared in-memory table dict."""

    def __init__(self, store: "FakeKVStore") -> None:
        self._store = store
        self._result: List[Tuple] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Optional[Tuple] = None) -> None:
        params = params or ()
        normalized = " ".join(sql.split())
        self._result = self._store.handle(normalized, params)

    def executemany(self, sql: str, seq: Any) -> None:
        for params in seq:
            self.execute(sql, params)

    def fetchone(self) -> Optional[Tuple]:
        return self._result[0] if self._result else None

    def fetchall(self) -> List[Tuple]:
        return list(self._result)


class FakeConn:
    def __init__(self, store: "FakeKVStore") -> None:
        self._store = store
        self.autocommit = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._store)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeKVStore:
    """In-memory backend understanding the KV + tiktoken queries under test."""

    def __init__(self) -> None:
        # table_name -> primary_key -> row dict
        self.config: Dict[str, Tuple[str, Optional[str]]] = {}  # key -> (value, desc)
        self.secrets: Dict[str, Tuple[str, bool]] = {}  # key -> (value, is_encrypted)
        # token counting: model/text driven; default counts whitespace words
        self.token_fn = lambda name, text: len(str(text).split())

    def handle(self, sql: str, params: Tuple) -> List[Tuple]:
        s = sql.lower()

        # --- token counting -------------------------------------------------
        if "create extension if not exists pg_tiktoken" in s:
            return []
        if "tiktoken_count(" in s:
            name, text = params
            return [(self.token_fn(name, text),)]
        if "from tiktoken_encode(" in s:
            name, text = params
            return [(self.token_fn(name, text),)]

        # --- llm_endpoint_models tokenizer lookup ---------------------------
        if "from llm_endpoint_models" in s:
            return []  # no DB tokenizer mapping in unit tests

        # --- com_config -----------------------------------------------------
        if "create table" in s and "com_config" in s:
            return []
        if "insert into com_config" in s and "do nothing" in s:
            key, value, desc = params
            self.config.setdefault(key, (value, desc))
            return []
        if "insert into com_config" in s and "do update" in s:
            key, value, desc = params
            self.config[key] = (value, desc)
            return []
        if "select config_value from com_config where config_key" in s:
            key = params[0]
            if key in self.config:
                return [(self.config[key][0],)]
            return []
        if "select config_key, config_value from com_config" in s:
            return [(k, v[0]) for k, v in sorted(self.config.items())]

        # --- com_secrets ----------------------------------------------------
        if "create table" in s and "com_secrets" in s:
            return []
        if "insert into com_secrets" in s:
            key, value, is_enc = params
            self.secrets[key] = (value, bool(is_enc))
            return []
        if "select secret_value, is_encrypted from com_secrets" in s:
            key = params[0]
            if key in self.secrets:
                v, enc = self.secrets[key]
                return [(v, enc)]
            return []

        return []


class FakePsycopgErrors:
    class UndefinedFunction(Exception):
        pass


class FakePsycopg:
    """Drop-in stand-in for the ``psycopg`` module in unit tests."""

    def __init__(self) -> None:
        self.store = FakeKVStore()
        self.errors = FakePsycopgErrors()

    def connect(self, *args: Any, **kwargs: Any) -> FakeConn:
        return FakeConn(self.store)
