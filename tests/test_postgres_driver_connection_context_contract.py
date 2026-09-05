from __future__ import annotations

from pg_llm_batch.postgres_driver_candidate import (
    REQUIRED_POSTGRES_DRIVER_CAPABILITIES,
)


def test_candidate_requires_transactional_connection_context_semantics() -> None:
    """Reject drivers whose context manager closes without commit/rollback parity."""
    assert "connection_context_commit_rollback" in REQUIRED_POSTGRES_DRIVER_CAPABILITIES
