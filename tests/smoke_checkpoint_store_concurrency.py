# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL acceptance for checkpoint concurrency and transaction coupling."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg

from pg_llm_batch.checkpoint_store import (
    CheckpointConflictError,
    PostgresBatchResultCheckpointStore,
)
from pg_llm_batch.result_streaming import BatchResultCheckpoint

DSN = os.environ.get(
    "PG_LLM_BATCH_CHECKPOINT_ACCEPTANCE_DSN",
    "postgresql://postgres@127.0.0.1:5432/postgres",
)


def checkpoint(
    batch_id: str,
    *,
    line_count: int,
    digest_character: str,
) -> BatchResultCheckpoint:
    """Build one deterministic valid checkpoint for live acceptance."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id=batch_id,
        endpoint_alias="default",
        file_kind="result",
        file_id=f"file-{batch_id}",
        file_line_number=line_count,
        batch_line_count=line_count,
        record_count=line_count,
        prefix_sha256=digest_character * 64,
    )


def run_simultaneous_saves(
    store: PostgresBatchResultCheckpointStore,
    consumer_name: str,
    candidates: tuple[BatchResultCheckpoint, BatchResultCheckpoint],
) -> tuple[object, object]:
    """Start two package-owned saves concurrently and return bounded outcomes."""
    barrier = Barrier(3)

    def save(candidate: BatchResultCheckpoint) -> object:
        barrier.wait(timeout=10)
        try:
            return store.save(consumer_name, candidate)
        except CheckpointConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, candidate) for candidate in candidates]
        barrier.wait(timeout=10)
        return tuple(future.result(timeout=20) for future in futures)


def assert_initial_race_contract(store: PostgresBatchResultCheckpointStore) -> None:
    """Prove identical first writers converge and conflicting writers fail closed."""
    identical = checkpoint("batch-race-identical", line_count=1, digest_character="d")
    identical_outcomes = run_simultaneous_saves(
        store,
        "consumer-race-identical",
        (identical, identical),
    )
    assert identical_outcomes == (identical, identical)
    assert store.load(
        "consumer-race-identical",
        identical.batch_id,
        identical.endpoint_alias,
    ) == identical

    candidate_a = checkpoint("batch-race-conflict", line_count=1, digest_character="e")
    candidate_b = checkpoint("batch-race-conflict", line_count=2, digest_character="f")
    conflict_outcomes = run_simultaneous_saves(
        store,
        "consumer-race-conflict",
        (candidate_a, candidate_b),
    )
    successes = [value for value in conflict_outcomes if isinstance(value, BatchResultCheckpoint)]
    conflicts = [value for value in conflict_outcomes if isinstance(value, CheckpointConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].reason in {"initial_checkpoint_race", "expected_previous_stale"}
    assert store.load(
        "consumer-race-conflict",
        candidate_a.batch_id,
        candidate_a.endpoint_alias,
    ) == successes[0]


def assert_compare_and_swap_contract(store: PostgresBatchResultCheckpointStore) -> None:
    """Prove exact expected-previous advancement and stale-writer refusal."""
    first = checkpoint("batch-cas", line_count=1, digest_character="1")
    second = checkpoint("batch-cas", line_count=2, digest_character="2")
    stale_candidate = checkpoint("batch-cas", line_count=3, digest_character="3")

    assert store.save("consumer-cas", first) == first
    assert store.save("consumer-cas", second, expected_previous=first) == second
    try:
        store.save("consumer-cas", stale_candidate, expected_previous=first)
    except CheckpointConflictError as exc:
        assert exc.reason == "expected_previous_stale"
    else:
        raise AssertionError("stale checkpoint writer unexpectedly overwrote durable state")
    assert store.load("consumer-cas", second.batch_id, second.endpoint_alias) == second


def assert_caller_transaction_contract(store: PostgresBatchResultCheckpointStore) -> None:
    """Prove business effect and checkpoint share caller commit/rollback authority."""
    rolled_back = checkpoint("batch-transaction-rollback", line_count=1, digest_character="4")
    committed = checkpoint("batch-transaction-commit", line_count=1, digest_character="5")

    with psycopg.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE checkpoint_acceptance_effects ("
                "effect_name TEXT PRIMARY KEY)"
            )
        connection.commit()

        with connection.cursor() as cursor:
            store.save_in_transaction(cursor, "consumer-transaction-rollback", rolled_back)
            cursor.execute(
                "INSERT INTO checkpoint_acceptance_effects (effect_name) VALUES (%s)",
                ("rollback-effect",),
            )
        connection.rollback()
        assert store.load(
            "consumer-transaction-rollback",
            rolled_back.batch_id,
            rolled_back.endpoint_alias,
        ) is None
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM checkpoint_acceptance_effects")
            assert cursor.fetchone() == (0,)

        with connection.cursor() as cursor:
            store.save_in_transaction(cursor, "consumer-transaction-commit", committed)
            cursor.execute(
                "INSERT INTO checkpoint_acceptance_effects (effect_name) VALUES (%s)",
                ("commit-effect",),
            )
        connection.commit()
        assert store.load(
            "consumer-transaction-commit",
            committed.batch_id,
            committed.endpoint_alias,
        ) == committed
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM checkpoint_acceptance_effects")
            assert cursor.fetchone() == (1,)


def main() -> None:
    """Run the live checkpoint-store acceptance contract."""
    store = PostgresBatchResultCheckpointStore(DSN)
    assert_initial_race_contract(store)
    assert_compare_and_swap_contract(store)
    assert_caller_transaction_contract(store)


if __name__ == "__main__":
    main()
