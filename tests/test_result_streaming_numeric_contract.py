# SPDX-License-Identifier: Apache-2.0
"""Focused regressions for strict result-streaming numeric contracts."""

from __future__ import annotations

from enum import IntEnum

import pytest

from pg_llm_batch import StreamingBatchAPIClient
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


class _PositiveIntEnum(IntEnum):
    """Represent an integer subclass that must not satisfy exact-int limits."""

    ONE = 1


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials without performing provider I/O."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="secret")


def test_streaming_parser_rejects_exponent_overflow_float() -> None:
    """JSON exponent overflow must not introduce a non-finite float record."""
    client = StreamingBatchAPIClient("postgresql://unit", _credentials)

    with pytest.raises(GatewayError, match="Malformed result line 1") as exc_info:
        client._parse_jsonl_line(
            b'{"value":1e999}',
            file_kind="result",
            line_number=1,
        )

    assert exc_info.value.response_data == {
        "file_kind": "result",
        "line_number": 1,
    }


def test_streaming_limits_reject_integer_subclasses() -> None:
    """Resource ceilings require exact ``int`` values, not integer subclasses."""
    with pytest.raises(ValidationError) as exc_info:
        StreamingBatchAPIClient(
            "postgresql://unit",
            _credentials,
            max_jsonl_records=_PositiveIntEnum.ONE,
        )

    assert exc_info.value.details["field"] == "max_jsonl_records"
