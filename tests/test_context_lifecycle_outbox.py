# SPDX-License-Identifier: Apache-2.0
"""Tests for the tenant-isolated durable Context lifecycle outbox."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox
from pg_llm_batch.context_lifecycle_evidence import ContextLifecycleEvidenceSeed
from pg_llm_batch.context_lifecycle_outbox import (
    ContextLifecycleOutboxConflictError,
    PostgresContextLifecycleOutboxStore,
    apply_context_lifecycle_outbox_schema,
)
from pg_llm_batch.exceptions import ConfigError, ValidationError


def evidence(*, evidence_id: str = "event-1", evidence_digest: str = "f" * 64) -> ContextLifecycleEvidenceSeed:
    """Build one content-free lifecycle evidence value for outbox tests."""
    return ContextLifecycleEvidenceSeed(
        evidence_id=evidence_id,
        event_type="batch.lifecycle.observed",
        tenant_scope_sha256="a" * 64,
        subject_ref_sha256="b" * 64,
        authority_ref_sha256="c" * 64,
        origin_ref_sha256="d" * 64,
        truth_status="observed",
        valid_time="2026-09-03T05:00:00Z",
        system_time="2026-09-03T05:00:01Z",
        provenance_ref_sha256="e" * 64,
        evidence_ref_sha256=evidence_digest,
    )


class FakeCursor:
    """Execute the bounded outbox persistence statements in memory."""

    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database
        self.result: Any = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Execute one expected tenant-qualified outbox statement."""
        normalized = " ".join(sql.split())
        parameters = params or ()
        self.database.calls.append((normalized, parameters))
        if normalized.startswith("SELECT set_config"):
            self.result = (parameters[0],)
            return
        if normalized.startswith("SELECT evidence_id"):
            self.result = self.database.rows.get(parameters)
            return
        if normalized.startswith("INSERT INTO llm_context_lifecycle_outbox"):
            tenant = parameters[0]
            seed_values = parameters[1:]
            key = (tenant, seed_values[0])
            if key in self.database.rows:
                self.result = None
                return
            self.database.rows[key] = seed_values
            self.result = (seed_values[0],)
            return
        if not parameters:
            self.result = None
            return
        raise AssertionError(normalized)

    def fetchone(self) -> Any:
        """Return the result produced by the preceding fake statement."""
        return self.result


class FakeConnection:
    """Expose cursor and commit accounting for one fake PostgreSQL database."""

    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database

    def __enter__(self) -> "FakeConnection":
        """Enter the fake connection context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Exit the fake connection context without swallowing exceptions."""
        return None

    def cursor(self) -> FakeCursor:
        """Create one cursor bound to the same fake database."""
        return FakeCursor(self.database)

    def commit(self) -> None:
        """Record one package-owned transaction commit."""
        self.database.commits += 1


class FakePsycopg:
    """Route package connection requests into one fake database."""

    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database

    def connect(self, dsn: str) -> FakeConnection:
        """Record the explicit DSN and return a fake connection."""
        self.database.dsns.append(dsn)
        return FakeConnection(self.database)


class FakeDatabase:
    """Hold deterministic durable rows and SQL evidence for outbox tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], tuple[Any, ...]] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.dsns: list[str] = []
        self.commits = 0


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> FakeDatabase:
    """Install deterministic psycopg behavior for each store test."""
    fake_database = FakeDatabase()
    monkeypatch.setattr(lifecycle_outbox, "psycopg", FakePsycopg(fake_database))
    monkeypatch.setattr(lifecycle_outbox, "_require_psycopg", lambda: None)
    return fake_database


def test_schema_contract_is_rls_scoped_and_has_rollback() -> None:
    """The durable outbox migration must be tenant-scoped and reversible."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    rollback = Path(lifecycle_outbox.ROLLBACK_PATH).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS llm_context_lifecycle_outbox" in migration
    assert "UNIQUE (tenant_scope, evidence_id)" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "current_setting('pg_llm_batch.tenant_scope', true)" in migration
    assert "DROP TABLE IF EXISTS llm_context_lifecycle_outbox" in rollback


@pytest.mark.parametrize("postgres_dsn", (None, "", "  \n"))
def test_store_requires_explicit_postgres_target(postgres_dsn: Any) -> None:
    """The durable store must never fall through to ambient libpq defaults."""
    with pytest.raises(ConfigError, match="Postgres DSN"):
        PostgresContextLifecycleOutboxStore(postgres_dsn)


def test_store_validates_trusted_tenant_before_sql() -> None:
    """Malformed local tenant scope fails before any database interaction."""
    with pytest.raises(ValidationError):
        PostgresContextLifecycleOutboxStore("postgresql://unit", tenant_scope=" bad")


def test_enqueue_is_idempotent_for_exact_replay(database: FakeDatabase) -> None:
    """An identical event replay reuses the durable row without rewriting it."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    seed = evidence()
    assert store.enqueue(seed) == seed
    assert store.enqueue(seed) == seed
    assert database.commits == 2
    statements = [sql for sql, _ in database.calls]
    assert sum(sql.startswith("INSERT INTO llm_context_lifecycle_outbox") for sql in statements) == 1


def test_enqueue_rejects_conflicting_replay(database: FakeDatabase) -> None:
    """Reusing an event id with changed evidence fails closed instead of overwriting."""
    store = PostgresContextLifecycleOutboxStore("postgresql://unit")
    first = evidence()
    store.enqueue(first)
    with pytest.raises(ContextLifecycleOutboxConflictError) as raised:
        store.enqueue(replace(first, evidence_ref_sha256="0" * 64))
    assert raised.value.reason == "conflicting_replay"
    assert store.load(first.evidence_id) == first


def test_enqueue_in_transaction_does_not_commit_caller_work(database: FakeDatabase) -> None:
    """A caller can atomically persist domain work and outbox evidence together."""
    store = PostgresContextLifecycleOutboxStore("postgresql://unit")
    cursor = FakeCursor(database)
    seed = evidence()
    assert store.enqueue_in_transaction(cursor, seed) == seed
    assert database.dsns == []
    assert database.commits == 0


def test_load_is_tenant_qualified_and_revalidates_rows(database: FakeDatabase) -> None:
    """Durable rows are isolated by local tenant scope and validated on read."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    seed = evidence()
    store.enqueue(seed)
    assert store.load(seed.evidence_id) == seed
    select_params = [params for sql, params in database.calls if sql.startswith("SELECT evidence_id")]
    assert ("tenant-a", seed.evidence_id) in select_params


def test_apply_schema_uses_explicit_migration_and_commit(
    database: FakeDatabase,
    tmp_path: Path,
) -> None:
    """Schema installation executes the selected migration in one explicit commit."""
    sql_path = tmp_path / "outbox.sql"
    sql_path.write_text("SELECT 1;", encoding="utf-8")
    apply_context_lifecycle_outbox_schema("postgresql://unit", str(sql_path))
    assert database.dsns == ["postgresql://unit"]
    assert database.calls == [("SELECT 1;", ())]
    assert database.commits == 1
