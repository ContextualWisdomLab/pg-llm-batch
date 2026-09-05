"""Thread-affine pg8000 candidate adapters for concurrency admission.

pg8000 1.31.5 declares DB-API ``threadsafety == 1``: threads may share the
module, but not connections. The portable candidate adapters intentionally do
not invent a stronger guarantee. This layer binds each candidate connection and
cursor to the thread that created it and fails before raw driver access when a
capability crosses that boundary.

The layer remains candidate-only. It is exercised by the exact-artifact
PostgreSQL smoke test and must not be treated as production dependency approval
until the remaining conninfo, error, recovery, package, SBOM, and provenance
gates pass on one immutable artifact.
"""

from __future__ import annotations

from threading import get_ident
from typing import Any

from .pg8000_driver_candidate_adapter import (
    Pg8000CandidateAdapterError,
    Pg8000CandidateConnectionAdapter,
    Pg8000CandidateCursorAdapter,
)


_THREAD_AFFINITY_ERROR = "PostgreSQL driver connection must not be shared across threads"
_CURSOR_THREAD_AFFINITY_ERROR = "PostgreSQL driver cursor must not be shared across threads"


class Pg8000ThreadAffineCandidateCursorAdapter(Pg8000CandidateCursorAdapter):
    """Bind one candidate cursor capability to its creating thread.

    The base adapter owns DB-API row, parameter, fetch-budget, and cleanup
    normalization. This subclass adds only the concurrency invariant required by
    pg8000's declared thread-safety level and performs the check before every raw
    cursor access.
    """

    def __init__(self, cursor: Any) -> None:
        """Retain one candidate cursor and bind its capability to this thread."""
        super().__init__(cursor)
        self._owner_thread_id = get_ident()

    def _require_owner_thread(self) -> None:
        """Reject cross-thread cursor use before touching driver-owned state."""
        if get_ident() != self._owner_thread_id:
            raise Pg8000CandidateAdapterError(_CURSOR_THREAD_AFFINITY_ERROR)

    def execute(
        self,
        query: str,
        params: object | None = None,
    ) -> Pg8000ThreadAffineCandidateCursorAdapter:
        """Execute only on the thread that owns the raw candidate cursor."""
        self._require_owner_thread()
        super().execute(query, params)
        return self

    def executemany(
        self,
        query: str,
        params_seq: object,
    ) -> Pg8000ThreadAffineCandidateCursorAdapter:
        """Execute a parameter sequence only on the cursor owner thread."""
        self._require_owner_thread()
        super().executemany(query, params_seq)
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        """Fetch one row only from the cursor owner thread."""
        self._require_owner_thread()
        return super().fetchone()

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        """Fetch one bounded page only from the cursor owner thread."""
        self._require_owner_thread()
        return super().fetchmany(size)

    def fetchall(self) -> list[tuple[object, ...]]:
        """Fetch an already bounded result only from the cursor owner thread."""
        self._require_owner_thread()
        return super().fetchall()

    def row_count(self) -> int | None:
        """Read affected-row evidence only from the cursor owner thread."""
        self._require_owner_thread()
        return super().row_count()

    def __enter__(self) -> Pg8000ThreadAffineCandidateCursorAdapter:
        """Enter the cursor context only on the owner thread."""
        self._require_owner_thread()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Release the raw cursor only on the thread that owns it."""
        self._require_owner_thread()
        return super().__exit__(exc_type, exc, traceback)


class Pg8000ThreadAffineCandidateConnectionAdapter(Pg8000CandidateConnectionAdapter):
    """Bind one candidate connection and its cursors to the creating thread.

    pg8000's DB-API metadata explicitly permits module sharing but not connection
    sharing. Serializing a shared connection with a lock would still exceed that
    contract, so this adapter rejects cross-thread connection access rather than
    treating mutual exclusion as proof of portability.
    """

    def __init__(self, connection: Any) -> None:
        """Retain one candidate connection and bind its session to this thread."""
        super().__init__(connection)
        self._owner_thread_id = get_ident()

    def _require_owner_thread(self) -> None:
        """Reject cross-thread connection use before touching raw driver state."""
        if get_ident() != self._owner_thread_id:
            raise Pg8000CandidateAdapterError(_THREAD_AFFINITY_ERROR)

    def cursor(self) -> Pg8000ThreadAffineCandidateCursorAdapter:
        """Create a thread-affine cursor on the exact owned connection."""
        self._require_owner_thread()
        return Pg8000ThreadAffineCandidateCursorAdapter(self._connection.cursor())

    def commit(self) -> None:
        """Commit only on the thread that owns the candidate connection."""
        self._require_owner_thread()
        super().commit()

    def rollback(self) -> None:
        """Roll back only on the thread that owns the candidate connection."""
        self._require_owner_thread()
        super().rollback()

    def set_autocommit(self, enabled: bool) -> None:
        """Change transaction mode only on the candidate connection owner thread."""
        self._require_owner_thread()
        super().set_autocommit(enabled)

    def close(self) -> None:
        """Close the raw candidate connection only from its owner thread."""
        self._require_owner_thread()
        super().close()

    def __enter__(self) -> Pg8000ThreadAffineCandidateConnectionAdapter:
        """Enter the candidate transaction context only on the owner thread."""
        self._require_owner_thread()
        return self
