# SPDX-License-Identifier: Apache-2.0
"""Contract tests for deterministic resumable provider-result checkpoints."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import replace
from typing import Any

import pytest

from pg_llm_batch import (
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
    StreamingBatchAPIClient,
)
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


class ChunkStream:
    """Expose caller-controlled chunks through the bounded stream contract."""

    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.requested_sizes: list[int] = []

    async def iter_chunked(self, size: int):
        """Yield configured chunks and record the requested byte ceiling."""
        self.requested_sizes.append(size)
        for chunk in self.chunks:
            yield chunk


class StreamResponse:
    """Minimal asynchronous response with deterministic close accounting."""

    def __init__(
        self,
        status: int,
        chunks: list[Any],
        *,
        content_length: int | None = None,
    ) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self.content = ChunkStream(chunks)
        self.content_length = content_length
        self.exit_count = 0

    async def __aenter__(self):
        """Enter the fake response context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Close the fake response exactly once per request context."""
        self.exit_count += 1
        return None


class RouteSession:
    """Return queued responses for exact GET URLs."""

    def __init__(self, routes: dict[str, list[StreamResponse]]) -> None:
        self.routes = {url: deque(responses) for url, responses in routes.items()}
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs: Any) -> StreamResponse:
        """Return the next configured response for ``url``."""
        self.calls.append(url)
        queue = self.routes.get(url)
        if not queue:
            raise AssertionError(f"no response left for GET {url}")
        return queue.popleft()

    async def close(self) -> None:
        """Satisfy the parent client session contract."""
        return None


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic HTTPS credentials for unit tests."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="secret")


def _json_response(payload: dict[str, Any]) -> StreamResponse:
    """Build one bounded control-plane JSON response."""
    encoded = json.dumps(payload).encode("utf-8")
    return StreamResponse(200, [encoded], content_length=len(encoded))


def _client(
    *,
    output_chunks: list[Any] | None = None,
    error_chunks: list[Any] | None = None,
    output_file_id: str | None = "out-1",
    error_file_id: str | None = "err-1",
    credentials: Any = _credentials,
    **kwargs: Any,
) -> tuple[StreamingBatchAPIClient, RouteSession, dict[str, StreamResponse]]:
    """Build a completed-batch client with deterministic provider routes."""
    status_payload: dict[str, Any] = {
        "id": "batch-1",
        "status": "completed",
        "request_counts": {"total": 3, "completed": 2, "failed": 1},
    }
    routes: dict[str, list[StreamResponse]] = {
        "https://gw.example/v1/batches/batch-1": [_json_response(status_payload)]
    }
    responses: dict[str, StreamResponse] = {}
    if output_file_id is not None:
        status_payload["output_file_id"] = output_file_id
        response = StreamResponse(200, output_chunks or [])
        responses["result"] = response
        routes[f"https://gw.example/v1/files/{output_file_id}/content"] = [response]
    if error_file_id is not None:
        status_payload["error_file_id"] = error_file_id
        response = StreamResponse(200, error_chunks or [])
        responses["error"] = response
        routes[f"https://gw.example/v1/files/{error_file_id}/content"] = [response]
    routes["https://gw.example/v1/batches/batch-1"] = [_json_response(status_payload)]
    client = StreamingBatchAPIClient("postgresql://unit", credentials, **kwargs)
    session = RouteSession(routes)
    client._session = session
    return client, session, responses


async def _collect(
    client: StreamingBatchAPIClient,
    *,
    resume_after: BatchResultCheckpoint | None = None,
) -> list[CheckpointedBatchResultRecord]:
    """Collect one bounded checkpointed stream for concise assertions."""
    return [
        item
        async for item in client.iter_checkpointed_batch_records(
            "batch-1",
            "default",
            resume_after=resume_after,
        )
    ]


async def test_checkpointed_records_are_chunk_independent_and_ordered():
    """Equivalent provider bytes produce identical checkpoints across chunking."""
    result = b'\n{"custom_id":"r1"}\r\n\n{"custom_id":"r2"}'
    error = b'{"custom_id":"e1","error":{"code":"bad"}}\n'
    first, _session, _responses = _client(
        output_chunks=[result],
        error_chunks=[error],
    )
    second, _session, _responses = _client(
        output_chunks=[result[:1], result[1:9], memoryview(result[9:])],
        error_chunks=[error[:7], error[7:]],
    )

    first_records = await _collect(first)
    second_records = await _collect(second)

    assert first_records == second_records
    assert [item.file_kind for item in first_records] == ["result", "result", "error"]
    assert [item.record for item in first_records] == [
        {"custom_id": "r1"},
        {"custom_id": "r2"},
        {"custom_id": "e1", "error": {"code": "bad"}},
    ]
    checkpoints = [item.checkpoint for item in first_records]
    assert [item.file_line_number for item in checkpoints] == [2, 4, 1]
    assert [item.batch_line_count for item in checkpoints] == [2, 4, 5]
    assert [item.record_count for item in checkpoints] == [1, 2, 3]
    assert [item.file_id for item in checkpoints] == ["out-1", "out-1", "err-1"]
    assert all(item.schema_version == 1 for item in checkpoints)
    assert all(re.fullmatch(r"[0-9a-f]{64}", item.prefix_sha256) for item in checkpoints)


async def test_resume_skips_acknowledged_record_and_preserves_later_checkpoints():
    """A trusted checkpoint suppresses acknowledged records after a clean rescan."""
    result = b'{"id":1}\n{"id":2}\n'
    error = b'{"id":3}\n'
    first, _session, _responses = _client(
        output_chunks=[result],
        error_chunks=[error],
    )
    complete = await _collect(first)

    resumed, session, _responses = _client(
        output_chunks=[result[:5], result[5:]],
        error_chunks=[error],
    )
    remaining = await _collect(resumed, resume_after=complete[0].checkpoint)

    assert remaining == complete[1:]
    assert session.calls == [
        "https://gw.example/v1/batches/batch-1",
        "https://gw.example/v1/files/out-1/content",
        "https://gw.example/v1/files/err-1/content",
    ]


async def test_resume_after_final_checkpoint_completes_without_replay():
    """Resuming from the final acknowledged record yields no duplicate records."""
    first, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_file_id=None,
    )
    complete = await _collect(first)
    resumed, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_file_id=None,
    )

    assert await _collect(resumed, resume_after=complete[-1].checkpoint) == []


async def test_resume_from_error_file_revalidates_result_prefix():
    """An error-file checkpoint binds all preceding result-file physical lines."""
    first, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_chunks=[b'{"id":2}\n{"id":3}\n'],
    )
    complete = await _collect(first)
    assert complete[1].file_kind == "error"

    resumed, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_chunks=[b'{"id":2}\n{"id":3}\n'],
    )

    assert await _collect(resumed, resume_after=complete[1].checkpoint) == complete[2:]


@pytest.mark.parametrize(
    "mutated_result",
    [
        b'{"secret":"changed-before-checkpoint"}\n{"id":2}\n',
        b'\n{"id":1}\n{"id":2}\n',
        b'{"id":1}\n{"id":999}\n',
    ],
)
async def test_resume_rejects_mutated_prefix_before_delivering_any_record(
    mutated_result: bytes,
):
    """Content, blank-line, or checkpoint-line mutation fails before replay."""
    original, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n{"id":2}\n{"id":3}\n'],
        error_file_id=None,
    )
    checkpoint = (await _collect(original))[1].checkpoint
    mutated, _session, responses = _client(
        output_chunks=[mutated_result],
        error_file_id=None,
    )
    iterator = mutated.iter_checkpointed_batch_records(
        "batch-1",
        "default",
        resume_after=checkpoint,
    )

    with pytest.raises(GatewayError, match="checkpoint does not match") as exc_info:
        await anext(iterator)

    assert exc_info.value.response_data == {
        "checkpoint_status": "mismatch",
        "file_kind": "result",
        "record_count": 2,
    }
    assert "changed-before-checkpoint" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert responses["result"].exit_count == 1


async def test_resume_rejects_missing_checkpoint_after_bounded_rescan():
    """A truncated provider stream cannot silently treat a checkpoint as current."""
    original, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n{"id":2}\n'],
        error_file_id=None,
    )
    checkpoint = (await _collect(original))[-1].checkpoint
    truncated, _session, responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_file_id=None,
    )

    with pytest.raises(GatewayError, match="checkpoint was not found") as exc_info:
        await _collect(truncated, resume_after=checkpoint)

    assert exc_info.value.response_data == {
        "checkpoint_status": "not_found",
        "file_kind": "result",
        "record_count": 2,
    }
    assert responses["result"].exit_count == 1


async def test_resume_rejects_changed_provider_file_identity():
    """A new file identifier cannot reuse a checkpoint from an older provider file."""
    original, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_file_id=None,
    )
    checkpoint = (await _collect(original))[0].checkpoint
    changed, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        output_file_id="out-2",
        error_file_id=None,
    )

    with pytest.raises(GatewayError, match="checkpoint does not match"):
        await _collect(changed, resume_after=checkpoint)


async def test_checkpoint_identity_mismatch_fails_before_credentials_or_network():
    """Local checkpoint identity is validated before any external side effect."""
    credential_calls: list[str] = []

    def credentials(alias: str) -> GatewayCredentials:
        credential_calls.append(alias)
        return _credentials(alias)

    client, session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_file_id=None,
        credentials=credentials,
    )
    checkpoint = BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-other",
        endpoint_alias="default",
        file_kind="result",
        file_id="out-1",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="0" * 64,
    )

    with pytest.raises(ValidationError) as exc_info:
        await _collect(client, resume_after=checkpoint)

    assert exc_info.value.field == "resume_after.batch_id"
    assert credential_calls == []
    assert session.calls == []


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"schema_version": True}, "schema_version"),
        ({"schema_version": 2}, "schema_version"),
        ({"batch_id": " bad"}, "batch_id"),
        ({"endpoint_alias": " default"}, "endpoint_alias"),
        ({"file_kind": "output"}, "file_kind"),
        ({"file_id": "bad/id"}, "file_id"),
        ({"file_line_number": 0}, "file_line_number"),
        ({"batch_line_count": True}, "batch_line_count"),
        ({"record_count": -1}, "record_count"),
        ({"batch_line_count": 1, "file_line_number": 2}, "batch_line_count"),
        ({"batch_line_count": 1, "record_count": 2}, "record_count"),
        ({"prefix_sha256": "A" * 64}, "prefix_sha256"),
        ({"prefix_sha256": "0" * 63}, "prefix_sha256"),
    ],
)
def test_checkpoint_fields_are_strict_and_non_coercive(
    changes: dict[str, Any],
    field: str,
):
    """Persisted checkpoint fields reject malformed or ambiguous values."""
    values: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": "batch-1",
        "endpoint_alias": "default",
        "file_kind": "result",
        "file_id": "out-1",
        "file_line_number": 1,
        "batch_line_count": 1,
        "record_count": 1,
        "prefix_sha256": "0" * 64,
    }
    values.update(changes)

    with pytest.raises(ValidationError) as exc_info:
        BatchResultCheckpoint(**values)

    assert exc_info.value.field == field


async def test_resume_after_requires_checkpoint_instance_before_network():
    """Mappings and lookalike objects cannot cross the trusted resume boundary."""
    client, session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_file_id=None,
    )

    with pytest.raises(ValidationError) as exc_info:
        await _collect(client, resume_after={"record_count": 1})  # type: ignore[arg-type]

    assert exc_info.value.field == "resume_after"
    assert session.calls == []


async def test_context_managed_checkpoint_stream_closes_after_early_exit():
    """The checkpoint context manager owns response cleanup on consumer break."""
    client, _session, responses = _client(
        output_chunks=[b'{"id":1}\n{"id":2}\n'],
        error_file_id=None,
    )

    async with client.open_checkpointed_batch_records(
        "batch-1",
        "default",
    ) as records:
        first = await anext(records)
        assert first.record == {"id": 1}
        assert responses["result"].exit_count == 0

    assert responses["result"].exit_count == 1


async def test_checkpoint_framing_distinguishes_termination_and_blank_lines():
    """Prefix digests bind physical framing rather than decoded JSON alone."""
    terminated, _session, _responses = _client(
        output_chunks=[b'{"id":1}\n'],
        error_file_id=None,
    )
    unterminated, _session, _responses = _client(
        output_chunks=[b'{"id":1}'],
        error_file_id=None,
    )
    leading_blank, _session, _responses = _client(
        output_chunks=[b'\n{"id":1}\n'],
        error_file_id=None,
    )

    digests = {
        (await _collect(terminated))[0].checkpoint.prefix_sha256,
        (await _collect(unterminated))[0].checkpoint.prefix_sha256,
        (await _collect(leading_blank))[0].checkpoint.prefix_sha256,
    }

    assert len(digests) == 3


def test_checkpoint_objects_are_immutable():
    """Persisted resume evidence cannot be changed after validation."""
    checkpoint = BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-1",
        endpoint_alias="default",
        file_kind="result",
        file_id="out-1",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="0" * 64,
    )

    with pytest.raises(ValidationError):
        replace(checkpoint, prefix_sha256="invalid")
    with pytest.raises(AttributeError):
        checkpoint.record_count = 2  # type: ignore[misc]
