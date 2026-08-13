# SPDX-License-Identifier: Apache-2.0
"""Coverage edges for resumable provider-result checkpoint validation."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from pg_llm_batch import BatchResultCheckpoint, StreamingBatchAPIClient
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.exceptions import ValidationError


class ByteStream:
    """Yield one bounded control-plane or provider-file byte sequence."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def iter_chunked(self, _size: int):
        """Yield the configured payload exactly once."""
        yield self.payload


class Response:
    """Provide the minimal asynchronous response contract used by the client."""

    def __init__(self, payload: bytes) -> None:
        self.status = 200
        self.headers: dict[str, str] = {}
        self.content_length = len(payload)
        self.content = ByteStream(payload)

    async def __aenter__(self):
        """Enter the fake response context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Leave the fake response context."""
        return None


class Session:
    """Serve queued exact-URL responses and retain network-call evidence."""

    def __init__(self) -> None:
        status = json.dumps(
            {
                "id": "batch-1",
                "status": "completed",
                "output_file_id": "out-1",
                "request_counts": {"total": 1, "completed": 1, "failed": 0},
            }
        ).encode("utf-8")
        self.routes = {
            "https://gw.example/v1/batches/batch-1": deque([Response(status)]),
            "https://gw.example/v1/files/out-1/content": deque(
                [Response(b'{"id":1}\n')]
            ),
        }
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs: Any) -> Response:
        """Return one response and record the attempted external call."""
        self.calls.append(url)
        return self.routes[url].popleft()

    async def close(self) -> None:
        """Satisfy the client session lifecycle contract."""
        return None


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic HTTPS credentials for unit tests."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="secret")


def client_with_session() -> tuple[StreamingBatchAPIClient, Session]:
    """Build a checkpoint client and expose its network-call evidence."""
    client = StreamingBatchAPIClient("postgresql://unit", credentials)
    session = Session()
    client._session = session
    return client, session


async def test_requested_endpoint_alias_must_be_pre_normalized_before_network():
    """Whitespace-normalized aliases fail locally instead of changing identity."""
    client, session = client_with_session()
    iterator = client.iter_checkpointed_batch_records("batch-1", " default")

    with pytest.raises(ValidationError) as exc_info:
        await anext(iterator)

    assert exc_info.value.details["field"] == "endpoint_alias"
    assert session.calls == []


async def test_resume_endpoint_identity_mismatch_fails_before_network():
    """A checkpoint from another endpoint cannot cross the local trust boundary."""
    client, session = client_with_session()
    checkpoint = BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-1",
        endpoint_alias="secondary",
        file_kind="result",
        file_id="out-1",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="0" * 64,
    )
    iterator = client.iter_checkpointed_batch_records(
        "batch-1",
        "default",
        resume_after=checkpoint,
    )

    with pytest.raises(ValidationError) as exc_info:
        await anext(iterator)

    assert exc_info.value.details["field"] == "resume_after.endpoint_alias"
    assert session.calls == []


def test_authoritative_docs_state_prefix_only_truncation_boundary():
    """Authoritative contracts must not overclaim unseen-suffix detection."""
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "docs/adr/0006-resumable-result-checkpoints.md",
        root / "docs/doctoring/resumable-result-checkpoints.md",
        root / "docs/result-streaming.md",
    )

    for path in paths:
        normalized = " ".join(path.read_text(encoding="utf-8").split()).lower()
        assert "strictly after the acknowledged checkpoint" in normalized
        assert "full-stream manifest" in normalized