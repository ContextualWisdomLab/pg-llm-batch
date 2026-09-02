# SPDX-License-Identifier: Apache-2.0
"""Contract tests for preflight batch-accumulator limit decisions."""

from __future__ import annotations

from pg_llm_batch.token_counter import BatchAccumulator


class _StaticCounter:
    """Expose only the configured limits required by ``BatchAccumulator``."""

    effective_limit = 5
    azure_max_records_per_file = 2
    azure_max_bytes_per_file = 10


def test_would_exceed_reports_oversized_first_record() -> None:
    """Preflight must report active token/byte ceilings before any record exists."""
    accumulator = BatchAccumulator(
        _StaticCounter(),  # type: ignore[arg-type]
        "provider-neutral-model",
        max_records=2,
        max_bytes=10,
    )

    assert accumulator.record_count == 0
    assert accumulator.would_exceed(tokens=6, byte_size=1) is True
    assert accumulator.would_exceed(tokens=1, byte_size=11) is True
    assert accumulator.would_exceed(tokens=5, byte_size=10) is False
