# SPDX-License-Identifier: Apache-2.0
"""Tests for durable tenant-isolated result-checkpoint persistence."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

import pg_llm_batch.checkpoint_store as checkpoint_store
from pg_llm_batch.checkpoint_store import (
    CheckpointConflictError,
    PostgresBatchResultCheckpointStore,
    apply_result_checkpoint_schema,
    validate_checkpoint_consumer_name,
)
from pg_llm_batch.exceptions import ConfigError, ValidationError
from pg_llm_batch.result_streaming import BatchResultCheckpoint

POSTGRES_BIGINT_MAX = (1 << 63) - 1


def checkpoint(
    *,
    record_count: int = 1,
    batch_line_count: int = 2,
    digest: str = "a" * 64,
) -> BatchResultCheckpoint:
    """Build one valid immutable checkpoint for persistence tests."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-1",
        endpoint_alias="default",
        file_kind="result",
        file_id="file-1",
        file_line_number=batch_line_count,
        batch_line_count=batch_line_count,
        record_count=record_count,
        prefix_sha256=digest,
    )


class FakeCursor:
    """Execute the checkpoint store's bounded SQL contract in memory."""

    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database
        self.result: Any = None

    def __enter__(self) -> "FakeCursor":
        """Enter the fake cursor context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Exit the fake cursor context."""
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Execute one expected tenant-qualified checkpoint statement."""
        normalized = " ".join(sql.split())
        parameters = params or ()
        self.database.calls.append((normalized, parameters))
        if normalized.startswith("SELECT set_config"):
            self.result = (parameters[0],)
            return
        if normalized.startswith("SELECT schema_version"):
            self.result = self.database.rows.get(parameters)
            return
        if normalized.startswith("INSERT INTO"):
            (
                tenant,
                consumer,
                alias,
                batch_id,
                schema,
                kind,
                file_id,
                file_line,
                batch_lines,
                records,
                digest,
            ) = parameters
            key = (tenant, consumer, alias, batch_id)
            if self.database.insert_conflict_without_row:
                self.database.insert_conflict_without_row = False
                self.result = None
                return
            if self.database.insert_race_row is not None:
                self.database.rows[key] = self.database.insert_race_row
                self.database.insert_race_row = None
                self.result = None
                return
            if key in self.database.rows:
                self.result = None
                return
            self.database.rows[key] = (
                schema,
                batch_id,
                alias,
                kind,
                file_id,
                file_line,
                batch_lines,
                records,
                digest,
            )
            self.result = (batch_id,)
            return
        if normalized.startswith("UPDATE"):
            (
                schema,
                kind,
                file_id,
                file_line,
                batch_lines,
                records,
                digest,
                tenant,
                consumer,
                alias,
                batch_id,
            ) = parameters
            self.database.rows[(tenant, consumer, alias, batch_id)] = (
                schema,
                batch_id,
                alias,
                kind,
                file_id,
                file_line,
                batch_lines,
                records,
                digest,
            )
            self.result = None
            return
        if not parameters:
            self.result = None
            return
        raise AssertionError(normalized)

    def fetchone(self) -> Any:
        """Return the result from the preceding fake statement."""
        return self.result


class FakeConnection:
    """Provide cursor and commit accounting for one fake database."""

    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database

    def __enter__(self) -> "FakeConnection":
        """Enter the fake connection context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Exit the fake connection context."""
        return None

    def cursor(self) -> FakeCursor:
        """Create one fake cursor."""
        return FakeCursor(self.database)

    def commit(self) -> None:
        """Record one explicit commit."""
        self.database.commits += 1


class FakePsycopg:
    """Connect checkpoint store calls to one in-memory fake database."""

    def __init__(self, database: "FakeDatabase") -> None:
        self.database = database

    def connect(self, dsn: str) -> FakeConnection:
        """Connect to one deterministic fake database."""
        self.database.dsns.append(dsn)
        return FakeConnection(self.database)


class FakeDatabase:
    """Hold deterministic rows, statements, and race simulation state."""

    def __init__(self) -> None:
        self.rows: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.dsns: list[str] = []
        self.commits = 0
        self.insert_race_row: tuple[Any, ...] | None = None
        self.insert_conflict_without_row = False


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> FakeDatabase:
    """Install one deterministic psycopg replacement for each test."""
    fake_database = FakeDatabase()
    monkeypatch.setattr(checkpoint_store, "psycopg", FakePsycopg(fake_database))
    monkeypatch.setattr(checkpoint_store, "_require_psycopg", lambda: None)
    return fake_database


def test_consumer_name_validation_is_strict_and_noncoercive() -> None:
    """Consumer names accept only the bounded durable-key grammar."""
    assert validate_checkpoint_consumer_name("worker.primary") == "worker.primary"
    for value in (None, 1, "", " leading", "bad/name", "a" * 129):
        with pytest.raises(ValidationError):
            validate_checkpoint_consumer_name(value)


@pytest.mark.parametrize("postgres_dsn", (None, "", " \t\n"))
def test_store_requires_an_explicit_nonblank_database_target(postgres_dsn: Any) -> None:
    """Missing DSNs must not fall through to libpq environment or local defaults."""
    with pytest.raises(ConfigError, match="Postgres DSN"):
        PostgresBatchResultCheckpointStore(postgres_dsn)


def test_store_validates_tenant_before_database_access() -> None:
    """An invalid trusted tenant never reaches PostgreSQL."""
    with pytest.raises(ValidationError):
        PostgresBatchResultCheckpointStore("postgresql://unit", tenant_scope=" bad")


def test_load_returns_none_and_uses_tenant_qualified_key(database: FakeDatabase) -> None:
    """Package-owned loads bind tenant context and every compound-key field."""
    store = PostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    assert store.load("worker-a", "batch-1", "default") is None
    assert database.dsns == ["postgresql://unit"]
    assert database.calls[0][1] == ("tenant-a",)
    assert database.calls[1][1] == (
        "tenant-a",
        "worker-a",
        "default",
        "batch-1",
    )


def test_load_in_transaction_uses_caller_cursor_without_commit(database: FakeDatabase) -> None:
    """Caller-owned reads remain inside the caller's transaction boundary."""
    database.rows[("tenant-a", "worker-a", "default", "batch-1")] = (
        1,
        "batch-1",
        "default",
        "result",
        "file-1",
        2,
        2,
        1,
        "a" * 64,
    )
    store = PostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    cursor = FakeCursor(database)
    assert store.load_in_transaction(cursor, "worker-a", "batch-1", "default") == checkpoint()
    assert database.dsns == []
    assert database.commits == 0


def test_load_revalidates_database_rows(database: FakeDatabase) -> None:
    """Malformed durable rows fail closed before becoming public checkpoints."""
    database.rows[("tenant-a", "worker-a", "default", "batch-1")] = (
        1,
        "batch-1",
        "default",
        "result",
        "file-1",
        2,
        2,
        1,
        "a" * 64,
    )
    store = PostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    assert store.load("worker-a", "batch-1", "default") == checkpoint()
    database.rows[("tenant-a", "worker-a", "default", "batch-1")] = (1, 2)
    with pytest.raises(RuntimeError, match="invalid shape"):
        store.load("worker-a", "batch-1", "default")


def test_load_rejects_noncanonical_identifiers_before_database(database: FakeDatabase) -> None:
    """Invalid batch and endpoint identities fail before SQL execution."""
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    with pytest.raises(ValidationError):
        store.load("worker-a", "bad/batch", "default")
    with pytest.raises(ValidationError):
        store.load("worker-a", "batch-1", "")
    with pytest.raises(ValidationError):
        store.load("worker-a", "batch-1", " default ")
    assert database.calls == []


def test_save_creates_and_idempotently_repeats_checkpoint(database: FakeDatabase) -> None:
    """Identical package-owned saves write once and remain idempotent."""
    store = PostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    first = checkpoint()
    assert store.save("worker-a", first) == first
    assert store.save("worker-a", first) == first
    assert database.commits == 2
    statements = [call[0] for call in database.calls]
    assert sum(item.startswith("INSERT") for item in statements) == 1
    assert sum(item.startswith("UPDATE") for item in statements) == 0


def test_save_in_transaction_does_not_commit_caller_work(database: FakeDatabase) -> None:
    """Caller-owned saves never commit unrelated local business effects."""
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    cursor = FakeCursor(database)
    assert store.save_in_transaction(cursor, "worker-a", checkpoint()) == checkpoint()
    assert database.dsns == []
    assert database.commits == 0


def test_save_handles_same_checkpoint_initial_insert_race(database: FakeDatabase) -> None:
    """A concurrent identical first writer remains an idempotent success."""
    first = checkpoint()
    database.insert_race_row = (
        first.schema_version,
        first.batch_id,
        first.endpoint_alias,
        first.file_kind,
        first.file_id,
        first.file_line_number,
        first.batch_line_count,
        first.record_count,
        first.prefix_sha256,
    )
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    assert store.save("worker-a", first) == first
    statements = [call[0] for call in database.calls]
    assert any("ON CONFLICT" in statement for statement in statements)
    assert sum(statement.startswith("SELECT schema_version") for statement in statements) == 2


def test_save_rejects_disappearing_insert_conflict_row(database: FakeDatabase) -> None:
    """A conflict without a visible durable row fails closed."""
    database.insert_conflict_without_row = True
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    with pytest.raises(RuntimeError, match="conflict row disappeared"):
        store.save("worker-a", checkpoint())
    assert database.rows == {}


def test_save_fails_closed_on_different_initial_insert_race(database: FakeDatabase) -> None:
    """A concurrent different first writer becomes one bounded conflict."""
    database.insert_race_row = (
        1,
        "batch-1",
        "default",
        "result",
        "file-1",
        3,
        3,
        2,
        "b" * 64,
    )
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    with pytest.raises(CheckpointConflictError) as raised:
        store.save("worker-a", checkpoint())
    assert raised.value.reason == "initial_checkpoint_race"
    assert database.commits == 0


def test_save_requires_missing_expected_checkpoint_to_remain_missing(database: FakeDatabase) -> None:
    """A claimed previous checkpoint cannot create a missing durable row."""
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    with pytest.raises(CheckpointConflictError) as raised:
        store.save(
            "worker-a",
            checkpoint(record_count=2, batch_line_count=3),
            expected_previous=checkpoint(),
        )
    assert raised.value.reason == "expected_previous_missing"
    assert raised.value.error_code == "CHECKPOINT_CONFLICT"
    assert database.rows == {}


def test_save_rejects_stale_or_forked_expected_checkpoint(database: FakeDatabase) -> None:
    """Writers cannot overwrite state they did not observe exactly."""
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    first = checkpoint()
    store.save("worker-a", first)
    advanced = checkpoint(record_count=2, batch_line_count=3, digest="b" * 64)
    with pytest.raises(CheckpointConflictError) as missing:
        store.save("worker-a", advanced)
    assert missing.value.reason == "expected_previous_stale"
    fork = replace(first, prefix_sha256="c" * 64)
    with pytest.raises(CheckpointConflictError) as stale:
        store.save("worker-a", advanced, expected_previous=fork)
    assert stale.value.reason == "expected_previous_stale"
    stored = database.rows[("standalone", "worker-a", "default", "batch-1")]
    assert stored[8] == "a" * 64


def test_save_rejects_regressive_counts(database: FakeDatabase) -> None:
    """Checkpoint advancement requires both logical and physical progress."""
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    first = checkpoint(record_count=2, batch_line_count=3)
    store.save("worker-a", first)
    for candidate in (
        checkpoint(record_count=2, batch_line_count=4, digest="b" * 64),
        checkpoint(record_count=3, batch_line_count=3, digest="c" * 64),
    ):
        with pytest.raises(CheckpointConflictError) as raised:
            store.save("worker-a", candidate, expected_previous=first)
        assert raised.value.reason == "checkpoint_regression"


def test_save_advances_exact_expected_checkpoint(database: FakeDatabase) -> None:
    """An exact compare-and-swap advances the tenant-qualified durable row."""
    store = PostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    first = checkpoint()
    second = checkpoint(record_count=2, batch_line_count=4, digest="b" * 64)
    store.save("worker-a", first)
    assert store.save("worker-a", second, expected_previous=first) == second
    assert database.commits == 2
    assert store.load("worker-a", "batch-1", "default") == second
    update = next(call for call in database.calls if call[0].startswith("UPDATE"))
    assert update[1][-4:] == ("tenant-a", "worker-a", "default", "batch-1")


def test_save_rejects_wrong_types_and_mismatched_expected_identity(database: FakeDatabase) -> None:
    """Type and identity mismatches fail before durable state access."""
    store = PostgresBatchResultCheckpointStore("postgresql://unit")
    with pytest.raises(ValidationError):
        store.save("worker-a", object())
    with pytest.raises(ValidationError):
        store.save("worker-a", checkpoint(), expected_previous=object())
    with pytest.raises(ValidationError):
        store.save(
            "worker-a",
            checkpoint(),
            expected_previous=replace(checkpoint(), batch_id="batch-2"),
        )
    assert database.calls == []


@pytest.mark.parametrize(
    ("changes", "expected_field"),
    (
        (
            {
                "file_line_number": POSTGRES_BIGINT_MAX + 1,
                "batch_line_count": POSTGRES_BIGINT_MAX + 1,
            },
            "checkpoint.file_line_number",
        ),
        (
            {"batch_line_count": POSTGRES_BIGINT_MAX + 1},
            "checkpoint.batch_line_count",
        ),
        (
            {
                "record_count": POSTGRES_BIGINT_MAX + 1,
                "batch_line_count": POSTGRES_BIGINT_MAX + 1,
            },
            "checkpoint.batch_line_count",
        ),
    ),
)
def test_save_rejects_checkpoint_counts_above_postgres_bigint_before_sql(
    changes: dict[str, int], expected_field: str
) -> None:
    """Oversized durable counts fail deterministically before tenant SQL binding."""
    candidate = replace(checkpoint(record_count=1, batch_line_count=1), **changes)
    store = PostgresBatchResultCheckpointStore("postgresql://unit")

    class RefusingCursor:
        def execute(self, _sql: str, _params: tuple[Any, ...] | None = None) -> None:
            raise AssertionError("database access occurred before validation")

        def fetchone(self) -> Any:
            raise AssertionError("database result read occurred before validation")

    with pytest.raises(ValidationError) as raised:
        store.save_in_transaction(RefusingCursor(), "worker-a", candidate)
    assert raised.value.details["field"] == expected_field


def test_save_rejects_oversized_expected_previous_before_sql() -> None:
    """Compare-and-swap evidence must also fit PostgreSQL before database access."""
    previous = replace(
        checkpoint(record_count=1, batch_line_count=1),
        file_line_number=POSTGRES_BIGINT_MAX + 1,
        batch_line_count=POSTGRES_BIGINT_MAX + 1,
    )
    candidate = replace(
        checkpoint(record_count=1, batch_line_count=1),
        file_line_number=POSTGRES_BIGINT_MAX,
        batch_line_count=POSTGRES_BIGINT_MAX,
        record_count=2,
        prefix_sha256="b" * 64,
    )
    store = PostgresBatchResultCheckpointStore("postgresql://unit")

    class RefusingCursor:
        def execute(self, _sql: str, _params: tuple[Any, ...] | None = None) -> None:
            raise AssertionError("database access occurred before validation")

        def fetchone(self) -> Any:
            raise AssertionError("database result read occurred before validation")

    with pytest.raises(ValidationError) as raised:
        store.save_in_transaction(
            RefusingCursor(),
            "worker-a",
            candidate,
            expected_previous=previous,
        )
    assert raised.value.details["field"] == "expected_previous.file_line_number"


def test_save_accepts_postgres_bigint_maximum_before_sql() -> None:
    """The exact signed BIGINT maximum remains a supported durable value."""
    candidate = replace(
        checkpoint(record_count=1, batch_line_count=1),
        file_line_number=POSTGRES_BIGINT_MAX,
        batch_line_count=POSTGRES_BIGINT_MAX,
        record_count=POSTGRES_BIGINT_MAX,
    )
    store = PostgresBatchResultCheckpointStore("postgresql://unit")

    class RefusingCursor:
        def execute(self, _sql: str, _params: tuple[Any, ...] | None = None) -> None:
            raise AssertionError("database access occurred")

        def fetchone(self) -> Any:
            raise AssertionError("database result read occurred")

    with pytest.raises(AssertionError, match="database access occurred"):
        store.save_in_transaction(RefusingCursor(), "worker-a", candidate)


def test_apply_schema_uses_explicit_migration(database: FakeDatabase, tmp_path: Any) -> None:
    """Operators may apply one explicitly selected migration file."""
    migration = tmp_path / "checkpoint.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    apply_result_checkpoint_schema("postgresql://unit", str(migration))
    assert database.calls[-1] == ("SELECT 1;", ())
    assert database.commits == 1


def test_apply_schema_uses_packaged_default(
    database: FakeDatabase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """The default installer reads the package-owned migration path."""
    migration = tmp_path / "default.sql"
    migration.write_text("SELECT 2;", encoding="utf-8")
    monkeypatch.setattr(checkpoint_store, "MIGRATION_PATH", migration)
    apply_result_checkpoint_schema("postgresql://unit")
    assert database.calls[-1] == ("SELECT 2;", ())
