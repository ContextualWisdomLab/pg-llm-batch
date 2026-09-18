# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for pg8000 no-parameter DB-API execution."""

from __future__ import annotations

from pg_llm_batch.pg8000_driver_candidate_adapter import Pg8000CandidateCursorAdapter


class _Pg8000NoParameterCursor:
    """Model pg8000 1.31.5 rejecting an explicit ``None`` argument container."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, *args: object) -> _Pg8000NoParameterCursor:
        """Record native execute arity and reproduce pg8000's ``len(None)`` failure."""
        self.calls.append((query, args))
        if args == (None,):
            raise TypeError("explicit None is not a pg8000 argument container")
        return self


def test_candidate_cursor_omits_argument_container_for_parameterless_sql() -> None:
    """Map the port's ``None`` sentinel to pg8000's native one-argument execute call."""
    raw = _Pg8000NoParameterCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)

    assert adapter.execute("SELECT current_database(), current_user") is adapter
    assert raw.calls == [("SELECT current_database(), current_user", ())]
