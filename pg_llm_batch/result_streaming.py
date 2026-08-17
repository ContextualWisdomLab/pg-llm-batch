# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Bounded result streaming with resumable checkpoint support."""

from __future__ import annotations

import json as _stdlib_json
from math import isfinite
from typing import Any

from . import result_streaming_checkpoint_impl as _impl
from .exceptions import ValidationError


def _parse_finite_json_number(token: str) -> float:
    """Parse one JSON floating-point token and reject non-finite results."""
    value = float(token)
    if not isfinite(value):
        raise ValueError("non-finite JSON number is not permitted")
    return value


class _StrictJsonProxy:
    """Inject the current finite-float contract into checkpoint JSON parsing."""

    @staticmethod
    def loads(document: str, **kwargs: Any) -> Any:
        """Decode JSON while rejecting finite-syntax exponent overflow."""
        kwargs.setdefault("parse_float", _parse_finite_json_number)
        return _stdlib_json.loads(document, **kwargs)


_impl.json = _StrictJsonProxy()

BatchResultRecord = _impl.BatchResultRecord
BatchResultCheckpoint = _impl.BatchResultCheckpoint
CheckpointedBatchResultRecord = _impl.CheckpointedBatchResultRecord
CHECKPOINT_SCHEMA_VERSION = _impl.CHECKPOINT_SCHEMA_VERSION
DEFAULT_MAX_JSONL_LINE_BYTES = _impl.DEFAULT_MAX_JSONL_LINE_BYTES
DEFAULT_MAX_JSONL_RECORDS = _impl.DEFAULT_MAX_JSONL_RECORDS
DEFAULT_MAX_JSONL_PHYSICAL_LINES = _impl.DEFAULT_MAX_JSONL_PHYSICAL_LINES


class StreamingBatchAPIClient(_impl.StreamingBatchAPIClient):
    """Streaming client preserving exact-int limits and resumable checkpoints."""

    def __init__(
        self,
        postgres_dsn: str,
        credentials: Any,
        *,
        max_jsonl_line_bytes: int = DEFAULT_MAX_JSONL_LINE_BYTES,
        max_jsonl_records: int = DEFAULT_MAX_JSONL_RECORDS,
        max_jsonl_physical_lines: int = DEFAULT_MAX_JSONL_PHYSICAL_LINES,
        **kwargs: Any,
    ) -> None:
        """Reject integer subclasses before delegating to checkpoint streaming."""
        for field, value in (
            ("max_jsonl_line_bytes", max_jsonl_line_bytes),
            ("max_jsonl_records", max_jsonl_records),
            ("max_jsonl_physical_lines", max_jsonl_physical_lines),
        ):
            if type(value) is not int or value <= 0:
                raise ValidationError(
                    field=field,
                    value=value,
                    reason="must be a positive integer",
                )
        super().__init__(
            postgres_dsn,
            credentials,
            max_jsonl_line_bytes=max_jsonl_line_bytes,
            max_jsonl_records=max_jsonl_records,
            max_jsonl_physical_lines=max_jsonl_physical_lines,
            **kwargs,
        )


__all__ = [
    "BatchResultCheckpoint",
    "BatchResultRecord",
    "CheckpointedBatchResultRecord",
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_MAX_JSONL_LINE_BYTES",
    "DEFAULT_MAX_JSONL_RECORDS",
    "DEFAULT_MAX_JSONL_PHYSICAL_LINES",
    "StreamingBatchAPIClient",
]
