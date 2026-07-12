# SPDX-License-Identifier: Apache-2.0
"""Unit tests for low-level database helpers and payload normalization."""

from __future__ import annotations

import pytest

from pg_llm_batch import db


class _Cursor:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def execute(self, sql, params=None):
        self.driver.executions.append((sql, params))

    def fetchone(self):
        return self.driver.row


class _Connection:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def cursor(self):
        return _Cursor(self.driver)

    def commit(self):
        self.driver.commits += 1


class _Psycopg:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.executions = []
        self.commits = 0
        self.connections = []

    def connect(self, dsn):
        if self.error:
            raise self.error
        self.connections.append(dsn)
        return _Connection(self)


def test_apply_schema_executes_exact_file(monkeypatch, tmp_path):
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE snake_case_name (id int);", encoding="utf-8")
    db.apply_schema("postgresql://x", str(schema))
    assert driver.executions == [("CREATE TABLE snake_case_name (id int);", None)]
    assert driver.commits == 1


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"text": '{"id":1}'}, '{"id":1}\n'),
        ({"text": ""}, ""),
        ('{"id":2}\n', '{"id":2}\n'),
        (123, "123\n"),
    ],
)
def test_load_virtual_payload_normalizes_jsonl(monkeypatch, stored, expected):
    driver = _Psycopg((stored,))
    monkeypatch.setattr(db, "psycopg", driver)
    assert db.load_virtual_payload("postgresql://x", "file-1") == expected
    assert driver.executions[0][1] == ("file-1",)


def test_load_virtual_payload_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(db, "psycopg", _Psycopg(None))
    assert db.load_virtual_payload("postgresql://x", "missing") is None


def test_model_metadata_normalizes_mode_and_handles_absence(monkeypatch):
    driver = _Psycopg((" CHAT ", "o200k_base"))
    monkeypatch.setattr(db, "psycopg", driver)
    assert db.get_model_metadata("postgresql://x", "gpt-4o") == {
        "mode": "chat",
        "tokenizer_model": "o200k_base",
    }

    driver.row = (None, None)
    assert db.get_model_metadata("postgresql://x", "unknown") == {
        "mode": None,
        "tokenizer_model": None,
    }
    driver.row = None
    assert db.get_model_metadata("postgresql://x", "unknown") is None
    assert db.get_model_metadata(None, "gpt-4o") is None
    assert db.get_model_metadata("postgresql://x", "") is None


def test_model_metadata_driver_failure_is_nonfatal(monkeypatch, caplog):
    monkeypatch.setattr(db, "psycopg", _Psycopg(error=OSError("database down")))
    with caplog.at_level("DEBUG"):
        assert db.get_model_metadata("postgresql://x", "gpt-4o") is None
    assert "database down" in caplog.text


def test_database_access_requires_psycopg(monkeypatch):
    monkeypatch.setattr(db, "psycopg", None)
    with pytest.raises(RuntimeError, match="psycopg is required"):
        db.load_virtual_payload("postgresql://x", "file")
