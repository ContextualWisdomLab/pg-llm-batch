# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Tenant-isolated PostgreSQL persistence for resumable result checkpoints."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from .db import (
    DEFAULT_TENANT_SCOPE,
    _require_psycopg,
    _set_transaction_tenant_scope,
    psycopg,
    validate_endpoint_alias,
    validate_remote_resource_id,
    validate_tenant_scope,
)
from .exceptions import ConfigError, PgLlmBatchError, ValidationError
from .postgres_driver_port import PostgresDriverPort
from .result_streaming import BatchResultCheckpoint

MIGRATION_PATH = (
    Path(__file__).with_name("migrations") / "0007_result_stream_checkpoints.sql"
)
MAX_CHECKPOINT_CONSUMER_CHARACTERS = 128
POSTGRES_BIGINT_MAX = (1 << 63) - 1
CHECKPOINT_CONSUMER_PATTERN = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_CHECKPOINT_CONSUMER_CHARACTERS - 1}}}\Z"
)
_CHECKPOINT_COLUMNS = (
    "schema_version, remote_batch_id, endpoint_alias, file_kind, file_id, "
    "file_line_number, batch_line_count, record_count, prefix_sha256"
)
_POSTGRES_BIGINT_CHECKPOINT_FIELDS = (
    "file_line_number",
    "batch_line_count",
    "record_count",
)


class CheckpointConflictError(PgLlmBatchError):
    """Raised when a durable checkpoint compare-and-swap cannot proceed safely."""

    def __init__(self, consumer_name: str, batch_id: str, reason: str) -> None:
        """Describe one bounded durable checkpoint concurrency conflict."""
        super().__init__(
            message="Result checkpoint update conflicted with durable state",
            error_code="CHECKPOINT_CONFLICT",
            details={
                "consumer_name": consumer_name,
                "batch_id": batch_id,
                "reason": reason,
            },
        )
        self.consumer_name = consumer_name
        self.batch_id = batch_id
        self.reason = reason


def validate_checkpoint_consumer_name(value: Any) -> str:
    """Validate one host-selected checkpoint consumer name without coercion."""
    if (
        not isinstance(value, str)
        or CHECKPOINT_CONSUMER_PATTERN.fullmatch(value) is None
    ):
        raise ValidationError(
            field="consumer_name",
            value=value,
            reason=(
                "must be 1-128 ASCII characters beginning with an alphanumeric "
                "character and containing only letters, digits, dot, underscore, "
                "colon, or hyphen"
            ),
        )
    return value


def _validated_postgres_dsn(value: Any) -> str:
    """Require an explicit nonblank database target without normalizing it."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "A Postgres DSN must be provided explicitly for checkpoint persistence"
        )
    return value


def _connect_postgres(
    postgres_dsn: str,
    postgres_driver: PostgresDriverPort | None,
) -> Any:
    """Connect through an injected driver while preserving the legacy default.

    The optional port lets one bounded persistence consumer migrate away from
    Psycopg without changing its SQL, transaction, tenant, or checkpoint
    semantics. Until the repository selects and validates a commercial
    replacement, omitting the port retains the current Psycopg path explicitly.
    """
    if postgres_driver is not None:
        return postgres_driver.connect(postgres_dsn)
    _require_psycopg()
    return psycopg.connect(postgres_dsn)


def _validated_checkpoint(value: Any, field: str) -> BatchResultCheckpoint:
    """Require one immutable checkpoint whose counters fit PostgreSQL storage."""
    if not isinstance(value, BatchResultCheckpoint):
        raise ValidationError(
            field=field,
            value=value,
            reason="must be a BatchResultCheckpoint",
        )
    for checkpoint_field in _POSTGRES_BIGINT_CHECKPOINT_FIELDS:
        count = getattr(value, checkpoint_field)
        if count > POSTGRES_BIGINT_MAX:
            raise ValidationError(
                field=f"{field}.{checkpoint_field}",
                value="<redacted>",
                reason=(
                    "must be no greater than PostgreSQL BIGINT maximum "
                    f"{POSTGRES_BIGINT_MAX}"
                ),
            )
    return value


def _validated_exact_endpoint_alias(value: Any) -> str:
    """Require one endpoint alias that is already in canonical form."""
    try:
        normalized = validate_endpoint_alias(value)
    except ValidationError as exc:
        raise ValidationError(
            field="endpoint_alias",
            value=value,
            reason="must be a supported endpoint alias",
        ) from exc
    if normalized != value:
        raise ValidationError(
            field="endpoint_alias",
            value=value,
            reason="must already be normalized without surrounding whitespace",
        )
    return normalized


def _validated_batch_id(value: Any) -> str:
    """Require one supported provider batch identifier."""
    try:
        return validate_remote_resource_id(value, "batch_id")
    except ValidationError as exc:
        raise ValidationError(
            field="batch_id",
            value=value,
            reason="must be a supported provider identifier",
        ) from exc


def _checkpoint_from_row(row: Any) -> BatchResultCheckpoint:
    """Revalidate one database row as an immutable checkpoint."""
    if not isinstance(row, (tuple, list)) or len(row) != 9:
        raise RuntimeError("result checkpoint row has an invalid shape")
    return BatchResultCheckpoint(
        schema_version=row[0],
        batch_id=row[1],
        endpoint_alias=row[2],
        file_kind=row[3],
        file_id=row[4],
        file_line_number=row[5],
        batch_line_count=row[6],
        record_count=row[7],
        prefix_sha256=row[8],
    )


def _checkpoint_values(checkpoint: BatchResultCheckpoint) -> tuple[Any, ...]:
    """Return one stable SQL value tuple for a validated checkpoint."""
    return (
        checkpoint.schema_version,
        checkpoint.file_kind,
        checkpoint.file_id,
        checkpoint.file_line_number,
        checkpoint.batch_line_count,
        checkpoint.record_count,
        checkpoint.prefix_sha256,
    )


def apply_result_checkpoint_schema(
    postgres_dsn: str,
    migration_path: Optional[str] = None,
    *,
    postgres_driver: PostgresDriverPort | None = None,
) -> None:
    """Apply the idempotent durable result-checkpoint migration."""
    dsn = _validated_postgres_dsn(postgres_dsn)
    path = Path(migration_path) if migration_path else MIGRATION_PATH
    sql = path.read_text(encoding="utf-8")
    with _connect_postgres(dsn, postgres_driver) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


class PostgresBatchResultCheckpointStore:
    """Persist tenant-qualified streaming checkpoints with compare-and-swap safety."""

    def __init__(
        self,
        postgres_dsn: str,
        *,
        tenant_scope: str = DEFAULT_TENANT_SCOPE,
        postgres_driver: PostgresDriverPort | None = None,
    ) -> None:
        """Bind one explicit database, tenant scope, and optional driver port."""
        self.postgres_dsn = _validated_postgres_dsn(postgres_dsn)
        self._postgres_driver = postgres_driver
        try:
            self.tenant_scope = validate_tenant_scope(tenant_scope)
        except ValidationError as exc:
            raise ValidationError(
                field="tenant_scope",
                value=tenant_scope,
                reason="must be a supported trusted tenant scope",
            ) from exc

    def load(
        self,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
    ) -> Optional[BatchResultCheckpoint]:
        """Load the current checkpoint in one package-owned transaction."""
        with _connect_postgres(self.postgres_dsn, self._postgres_driver) as conn:
            with conn.cursor() as cur:
                return self.load_in_transaction(
                    cur,
                    consumer_name,
                    batch_id,
                    endpoint_alias,
                )

    def load_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
    ) -> Optional[BatchResultCheckpoint]:
        """Load a checkpoint through a caller-owned database transaction.

        The caller owns commit and rollback. This method binds the store's trusted
        tenant scope with transaction-local PostgreSQL configuration before the
        tenant-qualified read.
        """
        consumer = validate_checkpoint_consumer_name(consumer_name)
        remote_batch_id = _validated_batch_id(batch_id)
        alias = _validated_exact_endpoint_alias(endpoint_alias)
        _set_transaction_tenant_scope(cursor, self.tenant_scope)
        cursor.execute(
            f"SELECT {_CHECKPOINT_COLUMNS} "
            "FROM llm_result_stream_checkpoints "
            "WHERE tenant_scope = %s "
            "AND checkpoint_consumer_name = %s "
            "AND endpoint_alias = %s "
            "AND remote_batch_id = %s",
            (self.tenant_scope, consumer, alias, remote_batch_id),
        )
        row = cursor.fetchone()
        return None if row is None else _checkpoint_from_row(row)

    def save(
        self,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: Optional[BatchResultCheckpoint] = None,
    ) -> BatchResultCheckpoint:
        """Create or advance a checkpoint in one package-owned transaction."""
        with _connect_postgres(self.postgres_dsn, self._postgres_driver) as conn:
            with conn.cursor() as cur:
                saved = self.save_in_transaction(
                    cur,
                    consumer_name,
                    checkpoint,
                    expected_previous=expected_previous,
                )
            conn.commit()
        return saved

    def save_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: Optional[BatchResultCheckpoint] = None,
    ) -> BatchResultCheckpoint:
        """Compare and swap a checkpoint in a caller-owned transaction.

        An identical repeat is idempotent. A different existing row requires the
        caller's exact previously loaded checkpoint and strictly increasing
        record and physical-line counts. Missing, stale, forked, or regressive
        updates fail without overwriting durable evidence. The caller owns commit
        and rollback, enabling local business effects and checkpoint advancement
        to share one PostgreSQL transaction.
        """
        consumer = validate_checkpoint_consumer_name(consumer_name)
        current_candidate = _validated_checkpoint(checkpoint, "checkpoint")
        previous_candidate = (
            None
            if expected_previous is None
            else _validated_checkpoint(expected_previous, "expected_previous")
        )
        if previous_candidate is not None and (
            previous_candidate.batch_id != current_candidate.batch_id
            or previous_candidate.endpoint_alias != current_candidate.endpoint_alias
        ):
            raise ValidationError(
                field="expected_previous",
                value=expected_previous,
                reason="must identify the same batch and endpoint as checkpoint",
            )

        _set_transaction_tenant_scope(cursor, self.tenant_scope)
        cursor.execute(
            f"SELECT {_CHECKPOINT_COLUMNS} "
            "FROM llm_result_stream_checkpoints "
            "WHERE tenant_scope = %s "
            "AND checkpoint_consumer_name = %s "
            "AND endpoint_alias = %s "
            "AND remote_batch_id = %s FOR UPDATE",
            (
                self.tenant_scope,
                consumer,
                current_candidate.endpoint_alias,
                current_candidate.batch_id,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            if previous_candidate is not None:
                raise CheckpointConflictError(
                    consumer,
                    current_candidate.batch_id,
                    "expected_previous_missing",
                )
            cursor.execute(
                "INSERT INTO llm_result_stream_checkpoints ("
                "tenant_scope, checkpoint_consumer_name, endpoint_alias, "
                "remote_batch_id, schema_version, file_kind, file_id, "
                "file_line_number, batch_line_count, record_count, "
                "prefix_sha256) VALUES ("
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_scope, checkpoint_consumer_name, "
                "endpoint_alias, remote_batch_id) DO NOTHING "
                "RETURNING remote_batch_id",
                (
                    self.tenant_scope,
                    consumer,
                    current_candidate.endpoint_alias,
                    current_candidate.batch_id,
                    *_checkpoint_values(current_candidate),
                ),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    f"SELECT {_CHECKPOINT_COLUMNS} "
                    "FROM llm_result_stream_checkpoints "
                    "WHERE tenant_scope = %s "
                    "AND checkpoint_consumer_name = %s "
                    "AND endpoint_alias = %s "
                    "AND remote_batch_id = %s FOR UPDATE",
                    (
                        self.tenant_scope,
                        consumer,
                        current_candidate.endpoint_alias,
                        current_candidate.batch_id,
                    ),
                )
                concurrent_row = cursor.fetchone()
                if concurrent_row is None:
                    raise RuntimeError(
                        "result checkpoint insert conflict row disappeared"
                    )
                concurrent = _checkpoint_from_row(concurrent_row)
                if concurrent == current_candidate:
                    return concurrent
                raise CheckpointConflictError(
                    consumer,
                    current_candidate.batch_id,
                    "initial_checkpoint_race",
                )
            return current_candidate

        durable = _checkpoint_from_row(row)
        if durable == current_candidate:
            return durable
        if previous_candidate is None or durable != previous_candidate:
            raise CheckpointConflictError(
                consumer,
                current_candidate.batch_id,
                "expected_previous_stale",
            )
        if (
            current_candidate.record_count <= durable.record_count
            or current_candidate.batch_line_count <= durable.batch_line_count
        ):
            raise CheckpointConflictError(
                consumer,
                current_candidate.batch_id,
                "checkpoint_regression",
            )
        cursor.execute(
            "UPDATE llm_result_stream_checkpoints SET "
            "schema_version = %s, file_kind = %s, file_id = %s, "
            "file_line_number = %s, batch_line_count = %s, "
            "record_count = %s, prefix_sha256 = %s, "
            "updated_at = NOW() "
            "WHERE tenant_scope = %s "
            "AND checkpoint_consumer_name = %s "
            "AND endpoint_alias = %s "
            "AND remote_batch_id = %s",
            (
                *_checkpoint_values(current_candidate),
                self.tenant_scope,
                consumer,
                current_candidate.endpoint_alias,
                current_candidate.batch_id,
            ),
        )
        return current_candidate
