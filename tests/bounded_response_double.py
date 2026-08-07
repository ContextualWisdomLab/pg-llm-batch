# SPDX-License-Identifier: Apache-2.0
"""Shared bounded-stream response doubles for provider-facing tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any


class BoundedJsonByteStream:
    """Expose one canonical JSON object through aiohttp-style byte chunks."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        """Serialize one mapping once so tests exercise the production byte boundary."""
        self.payload_bytes = json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.requested_sizes: list[int] = []

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        """Yield bounded chunks no larger than the requested positive size."""
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise AssertionError("bounded response chunk size must be a positive integer")
        self.requested_sizes.append(size)
        for offset in range(0, len(self.payload_bytes), size):
            yield self.payload_bytes[offset : offset + size]


def bind_bounded_json_response(response: Any, payload: Mapping[str, Any]) -> None:
    """Attach deterministic aiohttp-compatible content metadata to a response double."""
    content = BoundedJsonByteStream(payload)
    response.content = content
    response.content_length = len(content.payload_bytes)
