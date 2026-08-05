# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for byte-accurate memoryview stream accounting."""

from __future__ import annotations

from array import array
from collections.abc import AsyncIterator
from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


class _WideMemoryViewStream:
    """Yield four bytes represented by one multi-byte memoryview element."""

    async def iter_chunked(self, _size: int) -> AsyncIterator[memoryview]:
        """Yield a non-byte-formatted view whose element length understates bytes."""
        yield memoryview(array("I", [0x41414141]))


class _WideMemoryViewResponse:
    """Expose the wide memoryview through the response streaming contract."""

    status = 200
    content_length = None
    content = _WideMemoryViewStream()


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for constructing the client."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_memoryview_limit_uses_nbytes_not_element_count() -> None:
    """A multi-byte memoryview cannot bypass the decoded-byte resource limit."""
    client = BatchAPIClient("postgresql://example", _credentials)

    with pytest.raises(GatewayError, match="exceeded download limit") as exc_info:
        await client._read_bounded_utf8(
            _WideMemoryViewResponse(),
            "Batch status",
            max_bytes=3,
        )

    assert exc_info.value.response_data == {
        "limit_bytes": 3,
        "declared_bytes": None,
        "bytes_read": 0,
    }
    assert "AAAA" not in str(exc_info.value)
    assert "AAAA" not in repr(exc_info.value.response_data)
