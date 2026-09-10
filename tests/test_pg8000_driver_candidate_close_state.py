"""Recovery-state regressions for the candidate pg8000 connection adapter."""

from __future__ import annotations

import pytest

from pg_llm_batch.pg8000_driver_candidate_adapter import (
    Pg8000CandidateConnectionAdapter,
)


class _ProtocolCloseFailureConnection:
    """Model pg8000 closing its socket while protocol-level close reports failure."""

    def __init__(self) -> None:
        self.closed = False
        self.close_count = 0

    def close(self) -> None:
        """Release the underlying capability, then report the protocol failure."""
        self.close_count += 1
        self.closed = True
        raise RuntimeError("protocol close failed")


def test_candidate_marks_connection_closed_when_protocol_close_reports_failure() -> None:
    """A released pg8000 socket must not remain reusable after close raises."""
    raw = _ProtocolCloseFailureConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)

    assert adapter.is_closed() is False

    with pytest.raises(RuntimeError, match="protocol close failed"):
        adapter.close()

    assert raw.close_count == 1
    assert raw.closed is True
    assert adapter.is_closed() is True
