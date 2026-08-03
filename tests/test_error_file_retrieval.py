# SPDX-License-Identifier: Apache-2.0
"""Regression tests for output and provider error file retrieval."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


def _credentials(_alias: str) -> GatewayCredentials:
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


class Response:
    """Minimal asynchronous response with JSON and text representations."""

    def __init__(self, status: int, payload=None, *, text: str = "") -> None:
        self.status = status
        self.payload = payload
        self.text_value = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def json(self):
        return self.payload

    async def text(self):
        return self.text_value


class Session:
    """Route GET requests to canned responses by URL substring."""

    def __init__(self, routes) -> None:
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for needle, response in self.routes:
            if needle in url:
                return response
        raise AssertionError(f"no route for GET {url}")


def _jsonl(*records) -> str:
    return "\n".join(json.dumps(record) for record in records)


async def test_failed_batch_exposes_provider_error_file():
    """A failed batch remains diagnosable even when no output file exists."""
    session = Session(
        [
            (
                "/batches/failed",
                Response(
                    200,
                    {
                        "status": "failed",
                        "error_file_id": "errors-1",
                        "request_counts": {"total": 2, "completed": 0, "failed": 2},
                    },
                ),
            ),
            (
                "/files/errors-1/content",
                Response(
                    200,
                    text=_jsonl(
                        {"custom_id": "r1", "error": {"code": "invalid"}},
                        {"custom_id": "r2", "error": {"code": "rejected"}},
                    ),
                ),
            ),
        ]
    )
    client = BatchAPIClient("postgresql://x", _credentials)
    client._session = session

    result = await client.download_results("failed", "default")

    assert result["success"] is True
    assert result["batch_succeeded"] is False
    assert result["batch_status"] == "failed"
    assert result["response_count"] == 0
    assert result["error_count"] == 2
    assert result["has_errors"] is True
    assert result["errors"][0]["custom_id"] == "r1"


async def test_completed_batch_returns_output_and_error_records():
    """Partial provider failures are returned beside successful output records."""
    session = Session(
        [
            (
                "/batches/done",
                Response(
                    200,
                    {
                        "status": "completed",
                        "output_file_id": "output-1",
                        "error_file_id": "errors-1",
                        "request_counts": {"total": 2, "completed": 1, "failed": 1},
                    },
                ),
            ),
            (
                "/files/output-1/content",
                Response(200, text=_jsonl({"custom_id": "ok"})),
            ),
            (
                "/files/errors-1/content",
                Response(200, text=_jsonl({"custom_id": "bad", "error": {}})),
            ),
        ]
    )
    client = BatchAPIClient("postgresql://x", _credentials)
    client._session = session

    result = await client.download_results("done", "default")

    assert result["batch_succeeded"] is True
    assert result["response_count"] == 1
    assert result["error_count"] == 1
    assert result["responses"][0]["custom_id"] == "ok"
    assert result["errors"][0]["custom_id"] == "bad"


@pytest.mark.parametrize(
    ("content", "message", "details"),
    [
        (
            "{invalid",
            "Malformed error line",
            {"file_kind": "error", "line_number": 1},
        ),
        (
            "[]",
            "Non-object error line",
            {"file_kind": "error", "line_number": 1, "response_type": "list"},
        ),
    ],
)
async def test_error_files_require_valid_json_objects(content, message, details):
    """Corrupt provider diagnostics fail with source-aware structured errors."""
    session = Session(
        [
            (
                "/batches/failed",
                Response(
                    200,
                    {
                        "status": "failed",
                        "error_file_id": "errors-1",
                        "request_counts": {},
                    },
                ),
            ),
            ("/files/errors-1/content", Response(200, text=content)),
        ]
    )
    client = BatchAPIClient("postgresql://x", _credentials)
    client._session = session

    with pytest.raises(GatewayError, match=message) as exc_info:
        await client.download_results("failed", "default")

    assert exc_info.value.response_data == details


async def test_blank_lines_in_provider_files_are_skipped():
    """Blank lines inside a provider JSONL file are skipped, not parsed as records."""
    session = Session(
        [
            (
                "/batches/failed",
                Response(
                    200,
                    {
                        "status": "failed",
                        "error_file_id": "errors-1",
                        "request_counts": {"total": 2, "completed": 0, "failed": 2},
                    },
                ),
            ),
            (
                "/files/errors-1/content",
                Response(
                    200,
                    text='{"custom_id": "r1", "error": {"code": "invalid"}}\n\n'
                    '{"custom_id": "r2", "error": {"code": "rejected"}}',
                ),
            ),
        ]
    )
    client = BatchAPIClient("postgresql://x", _credentials)
    client._session = session

    result = await client.download_results("failed", "default")

    assert result["error_count"] == 2
    assert [record["custom_id"] for record in result["errors"]] == ["r1", "r2"]
