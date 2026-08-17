# SPDX-License-Identifier: Apache-2.0
"""Public package-root contract for durable result checkpoint storage."""

from __future__ import annotations

import pg_llm_batch
from pg_llm_batch import checkpoint_store


def test_checkpoint_store_api_is_exported_from_package_root() -> None:
    """Operators can install and construct the durable store from one public API."""
    public_symbols = (
        "CheckpointConflictError",
        "PostgresBatchResultCheckpointStore",
        "apply_result_checkpoint_schema",
        "validate_checkpoint_consumer_name",
    )

    for symbol_name in public_symbols:
        assert getattr(pg_llm_batch, symbol_name, None) is getattr(
            checkpoint_store, symbol_name
        )
        assert symbol_name in pg_llm_batch.__all__
