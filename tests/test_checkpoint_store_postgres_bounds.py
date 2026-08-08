# SPDX-License-Identifier: Apache-2.0
"""PostgreSQL storage-boundary tests for durable result checkpoints."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from pg_llm_batch import PostgresBatchResultCheckpointStore
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.result_streaming import BatchResultCheckpoint

POSTGRES_BIGINT_MAX = (1 << 63) - 1


class RefusingCursor:
    """Fail whenever invalid checkpoint input reaches database execution."""

    def execute(self, _sql: str, _params: tuple[Any, ...] | None = None) -> None:
        """Prove storage-bound validation completed before any SQL statement."""
        raise AssertionError("database access occurred before validation")

    def fetchone(self) -> Any:
        """Prevent accidental result access in a pre-database validation test."""
        raise AssertionError("database result read occurred before validation")


def checkpoint() -> BatchResultCheckpoint:
    """Build one valid checkpoint within PostgreSQL signed BIGINT limits."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-1",
        endpoint_alias="default",
        file_kind="result",
        file_id="file-1",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="a" * 64,
    )


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
    changes: dict[str, int],
    expected_field: str,
) -> None:
    """Oversized durable counts fail deterministically before tenant SQL binding."""
    candidate = replace(checkpoint(), **changes)
    store = PostgresBatchResultCheckpointStore("postgresql://unit")

    with pytest.raises(ValidationError) as raised:
        store.save_in_transaction(RefusingCursor(), "worker-a", candidate)

    assert raised.value.field == expected_field
    assert raised.value.reason == (
        f"must be no greater than PostgreSQL BIGINT maximum {POSTGRES_BIGINT_MAX}"
    )


def test_save_rejects_oversized_expected_previous_before_sql() -> None:
    """Compare-and-swap evidence must also fit PostgreSQL before database access."""
    previous = replace(
        checkpoint(),
        file_line_number=POSTGRES_BIGINT_MAX + 1,
        batch_line_count=POSTGRES_BIGINT_MAX + 1,
    )
    candidate = replace(
        checkpoint(),
        file_line_number=POSTGRES_BIGINT_MAX,
        batch_line_count=POSTGRES_BIGINT_MAX,
        record_count=2,
        prefix_sha256="b" * 64,
    )
    store = PostgresBatchResultCheckpointStore("postgresql://unit")

    with pytest.raises(ValidationError) as raised:
        store.save_in_transaction(
            RefusingCursor(),
            "worker-a",
            candidate,
            expected_previous=previous,
        )

    assert raised.value.field == "expected_previous.file_line_number"


def test_save_accepts_postgres_bigint_maximum_before_sql() -> None:
    """The exact signed BIGINT maximum remains a supported durable value."""
    candidate = replace(
        checkpoint(),
        file_line_number=POSTGRES_BIGINT_MAX,
        batch_line_count=POSTGRES_BIGINT_MAX,
        record_count=POSTGRES_BIGINT_MAX,
    )
    store = PostgresBatchResultCheckpointStore("postgresql://unit")

    with pytest.raises(AssertionError, match="database access occurred"):
        store.save_in_transaction(RefusingCursor(), "worker-a", candidate)
