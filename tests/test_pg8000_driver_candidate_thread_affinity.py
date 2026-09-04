"""Concurrency regressions for the candidate pg8000 DB-API boundary.

pg8000 1.31.5 declares DB-API ``threadsafety == 1``: threads may share the
module, but not connections. The admitted candidate boundary must therefore fail
before raw driver access when a connection or cursor capability crosses its
creating thread. This is candidate-admission evidence only; it does not promote
pg8000 into the production dependency graph.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import pytest

from pg_llm_batch.pg8000_driver_candidate_adapter import Pg8000CandidateAdapterError
from pg_llm_batch.pg8000_thread_affine_candidate_adapter import (
    Pg8000ThreadAffineCandidateConnectionAdapter,
    Pg8000ThreadAffineCandidateCursorAdapter,
)


class _RawCursor:
    def __init__(self) -> None:
        self.calls = 0
        self.rowcount = 1

    def execute(self, _query: str, _params: object | None = None) -> None:
        self.calls += 1

    def executemany(self, _query: str, _params_seq: object) -> None:
        self.calls += 1

    def fetchone(self) -> tuple[int]:
        self.calls += 1
        return (1,)

    def fetchmany(self, _size: int) -> list[tuple[int]]:
        self.calls += 1
        return [(1,)]

    def fetchall(self) -> list[tuple[int]]:
        self.calls += 1
        return [(1,)]

    def close(self) -> None:
        self.calls += 1


class _RawConnection:
    def __init__(self) -> None:
        self.calls = 0
        self._autocommit = False

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        self.calls += 1
        self._autocommit = value

    def cursor(self) -> _RawCursor:
        self.calls += 1
        return _RawCursor()

    def commit(self) -> None:
        self.calls += 1

    def rollback(self) -> None:
        self.calls += 1

    def close(self) -> None:
        self.calls += 1


def _run_on_worker(operation: Callable[[], object]) -> object:
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(operation).result()


@pytest.mark.parametrize(
    "operation",
    ("cursor", "commit", "rollback", "set_autocommit", "close"),
)
def test_candidate_connection_rejects_cross_thread_driver_access(operation: str) -> None:
    raw = _RawConnection()
    adapter = Pg8000ThreadAffineCandidateConnectionAdapter(raw)

    callbacks: dict[str, Callable[[], object]] = {
        "cursor": adapter.cursor,
        "commit": adapter.commit,
        "rollback": adapter.rollback,
        "set_autocommit": lambda: adapter.set_autocommit(True),
        "close": adapter.close,
    }

    with pytest.raises(
        Pg8000CandidateAdapterError,
        match="must not be shared across threads",
    ):
        _run_on_worker(callbacks[operation])

    assert raw.calls == 0


@pytest.mark.parametrize(
    "operation",
    ("execute", "executemany", "fetchone", "fetchmany", "fetchall", "row_count", "close"),
)
def test_candidate_cursor_rejects_cross_thread_driver_access(operation: str) -> None:
    raw = _RawCursor()
    adapter = Pg8000ThreadAffineCandidateCursorAdapter(raw)

    callbacks: dict[str, Callable[[], object]] = {
        "execute": lambda: adapter.execute("SELECT %s", (1,)),
        "executemany": lambda: adapter.executemany("SELECT %s", [(1,)]),
        "fetchone": adapter.fetchone,
        "fetchmany": lambda: adapter.fetchmany(1),
        "fetchall": adapter.fetchall,
        "row_count": adapter.row_count,
        "close": lambda: adapter.__exit__(None, None, None),
    }

    with pytest.raises(
        Pg8000CandidateAdapterError,
        match="must not be shared across threads",
    ):
        _run_on_worker(callbacks[operation])

    assert raw.calls == 0
