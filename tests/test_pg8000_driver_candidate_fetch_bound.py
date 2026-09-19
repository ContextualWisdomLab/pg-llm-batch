"""Regression contract for bounded pg8000 candidate fetches.

The PostgreSQL driver port promises that ``fetchmany(size)`` returns at most the
requested row budget. A candidate that over-delivers rows or returns an unsized
iterable must fail at the anti-corruption boundary rather than expanding or
obscuring an application resource budget.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from pg_llm_batch.pg8000_driver_candidate_adapter import (
    Pg8000CandidateAdapterError,
    Pg8000CandidateCursorAdapter,
)


class _OverDeliveringCursor:
    """Return more rows than requested to model a non-conforming DB-API candidate."""

    def fetchmany(self, size: int) -> list[list[int]]:
        assert size == 1
        return [[1], [2]]


class _UnsizedCursor:
    """Return an iterable whose cardinality cannot be checked before materialization."""

    def fetchmany(self, size: int) -> Iterator[list[int]]:
        assert size == 1
        yield [1]


def test_candidate_fetchmany_rejects_driver_overdelivery() -> None:
    adapter = Pg8000CandidateCursorAdapter(_OverDeliveringCursor())

    with pytest.raises(
        Pg8000CandidateAdapterError,
        match="fetch result exceeds requested size",
    ):
        adapter.fetchmany(1)


def test_candidate_fetchmany_rejects_unsized_driver_results() -> None:
    adapter = Pg8000CandidateCursorAdapter(_UnsizedCursor())

    with pytest.raises(
        Pg8000CandidateAdapterError,
        match="fetch result is invalid",
    ):
        adapter.fetchmany(1)
