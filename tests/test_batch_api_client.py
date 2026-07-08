# SPDX-License-Identifier: Apache-2.0
"""Unit tests for submit/poll/retrieve against a mocked Batch API."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials


class FakeResponse:
    def __init__(self, status: int, payload=None, text: str = "") -> None:
        self.status = status
        self._payload = payload
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class FakeSession:
    """Routes requests to canned responses keyed by a URL substring."""

    def __init__(self, routes) -> None:
        self.routes = routes
        self.calls = []

    def _match(self, method: str, url: str) -> FakeResponse:
        for (m, needle), resp in self.routes.items():
            if m == method and needle in url:
                return resp
        raise AssertionError(f"no route for {method} {url}")

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._match("POST", url)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._match("GET", url)

    async def close(self):
        return None


def _creds(_alias: str) -> GatewayCredentials:
    return GatewayCredentials(url="https://gw.example/v1", api_key="sk-test")


@pytest.fixture()
def patch_payload(monkeypatch):
    monkeypatch.setattr(
        client_mod,
        "load_virtual_payload",
        lambda dsn, file_id: '{"custom_id":"r1"}\n',
    )


async def test_upload_and_create_batch(patch_payload):
    session = FakeSession(
        {
            ("POST", "/files"): FakeResponse(200, {"id": "file-123"}),
            ("POST", "/batches"): FakeResponse(
                201, {"id": "batch-xyz", "status": "validating"}
            ),
        }
    )
    client = BatchAPIClient("postgresql://x", _creds)
    client._session = session

    uploaded = await client.upload_jsonl("memory://abc", "default")
    assert uploaded["id"] == "file-123"

    job = await client.create_batch_job("file-123", "default")
    assert job["id"] == "batch-xyz"
    # verify the request body carried the input_file_id
    post_batches = [c for c in session.calls if c[0] == "POST" and "/batches" in c[1]]
    assert post_batches[0][2]["json"]["input_file_id"] == "file-123"


async def test_poll_computes_progress():
    session = FakeSession(
        {
            ("GET", "/batches/batch-xyz"): FakeResponse(
                200,
                {
                    "id": "batch-xyz",
                    "status": "in_progress",
                    "request_counts": {"total": 4, "completed": 2, "failed": 1},
                },
            ),
        }
    )
    client = BatchAPIClient("postgresql://x", _creds)
    client._session = session
    status = await client.get_batch_status("batch-xyz", "default")
    assert status["progress_percentage"] == 75.0
    assert status["is_complete"] is False


async def test_retrieve_downloads_and_parses():
    output_lines = "\n".join(
        json.dumps({"custom_id": f"r{i}", "response": {"body": {}}}) for i in range(3)
    )
    session = FakeSession(
        {
            ("GET", "/batches/batch-done"): FakeResponse(
                200,
                {
                    "id": "batch-done",
                    "status": "completed",
                    "output_file_id": "out-1",
                    "request_counts": {"total": 3, "completed": 3, "failed": 0},
                },
            ),
            ("GET", "/files/out-1/content"): FakeResponse(200, text=output_lines),
        }
    )
    client = BatchAPIClient("postgresql://x", _creds)
    client._session = session
    result = await client.download_results("batch-done", "default")
    assert result["success"] is True
    assert result["response_count"] == 3
    assert result["responses"][0]["custom_id"] == "r0"


async def test_retrieve_returns_incomplete_when_not_done():
    session = FakeSession(
        {
            ("GET", "/batches/pending"): FakeResponse(
                200, {"id": "pending", "status": "in_progress", "request_counts": {}}
            ),
        }
    )
    client = BatchAPIClient("postgresql://x", _creds)
    client._session = session
    result = await client.download_results("pending", "default")
    assert result["success"] is False
    assert "not complete" in result["reason"]
