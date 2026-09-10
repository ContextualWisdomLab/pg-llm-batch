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


class _Driver:
    """Minimal database driver fake for default and injected port paths."""

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


def _use_default_driver(monkeypatch: pytest.MonkeyPatch, driver: _Driver) -> None:
    """Route the package default through the canonical runtime selector seam."""
    monkeypatch.setattr(db, "retained_postgres_driver", lambda: driver)


def _deny_default_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if an explicitly injected database operation reacquires the default."""

    def fail_default_driver():
        raise AssertionError("default PostgreSQL runtime driver was reached")

    monkeypatch.setattr(db, "retained_postgres_driver", fail_default_driver)


def test_apply_schema_executes_packaged_file(monkeypatch, tmp_path):
    driver = _Driver()
    _use_default_driver(monkeypatch, driver)
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE snake_case_name (id int);", encoding="utf-8")
    monkeypatch.setattr(db, "SCHEMA_PATH", schema)

    db.apply_schema("postgresql://x")

    assert driver.executions == [("CREATE TABLE snake_case_name (id int);", None)]
    assert driver.commits == 1


def test_apply_schema_uses_injected_driver_without_default_driver(monkeypatch, tmp_path):
    """Schema bootstrap must honor an injected driver without hidden reacquisition."""
    driver = _Driver()
    _deny_default_driver(monkeypatch)
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE snake_case_name (id int);", encoding="utf-8")
    monkeypatch.setattr(db, "SCHEMA_PATH", schema)

    db.apply_schema("postgresql://x", postgres_driver=driver)

    assert driver.connections == ["postgresql://x"]
    assert driver.executions == [("CREATE TABLE snake_case_name (id int);", None)]
    assert driver.commits == 1


def test_apply_schema_refuses_caller_selected_sql(monkeypatch, tmp_path):
    """Caller-controlled local files must not acquire arbitrary SQL authority."""
    driver = _Driver()
    _use_default_driver(monkeypatch, driver)
    untrusted_schema = tmp_path / "untrusted.sql"
    untrusted_schema.write_text("DROP TABLE llm_requests;", encoding="utf-8")

    with pytest.raises(TypeError):
        db.apply_schema("postgresql://x", str(untrusted_schema))

    assert driver.connections == []
    assert driver.executions == []
    assert driver.commits == 0


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"text": '{"id":1}\n', "line_count": 1}, '{"id":1}\n'),
        ({"text": "", "line_count": 0}, ""),
    ],
)
def test_load_virtual_payload_preserves_canonical_jsonl(monkeypatch, stored, expected):
    driver = _Driver((stored,))
    _use_default_driver(monkeypatch, driver)
    assert db.load_virtual_payload("postgresql://x", "file-1") == expected
    assert driver.executions[0][1] == ("file-1",)


def test_load_virtual_payload_uses_injected_driver_without_default_driver(monkeypatch):
    """Virtual payload reads must honor the explicit driver boundary."""
    stored = {"text": '{"id":1}\n', "line_count": 1}
    driver = _Driver((stored,))
    _deny_default_driver(monkeypatch)

    assert (
        db.load_virtual_payload(
            "postgresql://x",
            "file-1",
            postgres_driver=driver,
        )
        == '{"id":1}\n'
    )
    assert driver.connections == ["postgresql://x"]
    assert driver.executions[0][1] == ("file-1",)


def test_load_virtual_payload_returns_none_when_missing(monkeypatch):
    driver = _Driver(None)
    _use_default_driver(monkeypatch, driver)
    assert db.load_virtual_payload("postgresql://x", "missing") is None


def test_model_metadata_normalizes_mode_and_handles_absence(monkeypatch):
    driver = _Driver((" CHAT ", "o200k_base"))
    _use_default_driver(monkeypatch, driver)
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


def test_model_metadata_uses_injected_driver_without_default_driver(monkeypatch):
    """Tokenizer metadata lookup must honor the explicit driver boundary."""
    driver = _Driver((" CHAT ", "o200k_base"))
    _deny_default_driver(monkeypatch)

    assert db.get_model_metadata(
        "postgresql://x",
        "gpt-4o",
        postgres_driver=driver,
    ) == {
        "mode": "chat",
        "tokenizer_model": "o200k_base",
    }
    assert driver.connections == ["postgresql://x"]


def test_model_metadata_driver_failure_is_nonfatal(monkeypatch, caplog):
    driver = _Driver(error=OSError("database down"))
    _use_default_driver(monkeypatch, driver)
    with caplog.at_level("DEBUG"):
        assert db.get_model_metadata("postgresql://x", "gpt-4o") is None
    assert "database down" in caplog.text


def test_database_access_requires_runtime_driver(monkeypatch):
    """Default database access must fail when the canonical runtime selector fails."""

    def fail_default_driver():
        raise RuntimeError("PostgreSQL runtime driver is required")

    monkeypatch.setattr(db, "retained_postgres_driver", fail_default_driver)
    with pytest.raises(RuntimeError, match="runtime driver is required"):
        db.load_virtual_payload("postgresql://x", "file")
