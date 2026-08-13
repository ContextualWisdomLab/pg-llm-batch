# SPDX-License-Identifier: Apache-2.0
"""Confidentiality regressions for durable checkpoint validation evidence."""

from __future__ import annotations

import pytest

from pg_llm_batch.checkpoint_store import POSTGRES_BIGINT_MAX, _validated_checkpoint
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.result_streaming import BatchResultCheckpoint


def test_oversized_checkpoint_counter_is_not_copied_into_validation_evidence() -> None:
    """Rejected operational counters must not escape through exception evidence."""
    rejected_count = POSTGRES_BIGINT_MAX + 104_729
    checkpoint = BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-1",
        endpoint_alias="default",
        file_kind="result",
        file_id="file-1",
        file_line_number=rejected_count,
        batch_line_count=rejected_count,
        record_count=1,
        prefix_sha256="a" * 64,
    )

    with pytest.raises(ValidationError) as raised:
        _validated_checkpoint(checkpoint, "checkpoint")

    rejected_text = str(rejected_count)
    assert rejected_text not in str(raised.value)
    assert rejected_text not in repr(raised.value)
    assert raised.value.details["value"] == "<redacted>"
    assert rejected_text not in repr(raised.value.details)
