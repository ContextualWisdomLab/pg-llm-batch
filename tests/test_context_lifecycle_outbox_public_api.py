# SPDX-License-Identifier: Apache-2.0
"""Public API contract for the durable Context lifecycle outbox."""

from __future__ import annotations

import pg_llm_batch
import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


def test_lifecycle_outbox_is_available_from_package_root() -> None:
    """Consumers should not need a private module path for the durable boundary."""
    expected = {
        "ContextLifecycleOutboxConflictError": (
            lifecycle_outbox.ContextLifecycleOutboxConflictError
        ),
        "PostgresContextLifecycleOutboxStore": (
            lifecycle_outbox.PostgresContextLifecycleOutboxStore
        ),
        "apply_context_lifecycle_outbox_schema": (
            lifecycle_outbox.apply_context_lifecycle_outbox_schema
        ),
    }
    for symbol_name, implementation in expected.items():
        assert getattr(pg_llm_batch, symbol_name) is implementation
        assert symbol_name in pg_llm_batch.__all__
