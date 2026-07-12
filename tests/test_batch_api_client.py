# SPDX-License-Identifier: Apache-2.0
"""Unit tests for submit/poll/retrieve against a mocked Batch API."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import (
    BatchAPIClient,
    GatewayCredentials,
    config_credentials_provider,
)
from pg_llm_batch.exceptions import GatewayError


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


def test_credentials_provider_uses_alias_then_default_and_explains_missing():
    class Config:
        def __init__(self, values):
            self.values = values

        def get(self, category, key, default):
            assert category == "gateway"
            return self.values.get(key, default)

    class Secrets:
        def require_secret(self, key):
            return f"secret-for:{key}"

    provider = config_credentials_provider(
        Config({"blue": "https://blue.example/v1/", "base_url": "https://base/"}),
        Secrets(),
    )
    assert provider("blue") == GatewayCredentials(
        url="https://blue.example/v1", api_key="secret-for:gateway_api_key.blue"
    )
    assert provider("green").url == "https://base"

    missing = config_credentials_provider(Config({}), Secrets())
    with pytest.raises(GatewayError, match="No gateway base_url configured"):
        missing("unknown")


def test_client_validates_memory_identifiers_and_headers():
    with pytest.raises(RuntimeError, match="Postgres DSN"):
        BatchAPIClient("", _creds)
    client = BatchAPIClient("postgresql://x", _creds)
    assert client._resolve_memory_identifier("memory://file-1") == "file-1"
    for invalid in ("memory://", "/tmp/file.jsonl"):
        with pytest.raises(RuntimeError, match="memory://"):
            client._resolve_memory_identifier(invalid)
    assert client._headers("key") == {
        "Authorization": "Bearer key",
        "User-Agent": "pg-llm-batch",
    }
    assert client._headers("key", json_body=True)["Content-Type"] == "application/json"


async def test_client_context_and_lazy_session(monkeypatch):
    sessions = []

    class Session:
        def __init__(self):
            self.closed = False
            sessions.append(self)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", Session)
    client = BatchAPIClient("postgresql://x", _creds)
    await client.__aexit__(None, None, None)
    first = client._get_session()
    assert client._get_session() is first
    await client.__aexit__(None, None, None)
    assert first.closed is True
    assert client._session is None
    async with client as entered:
        assert entered is client
        assert client._session is sessions[-1]
    assert sessions[-1].closed is True


async def test_payload_missing_and_upload_error(monkeypatch):
    monkeypatch.setattr(client_mod, "load_virtual_payload", lambda _dsn, _id: None)
    client = BatchAPIClient("postgresql://x", _creds)
    with pytest.raises(FileNotFoundError, match="file_id=missing"):
        await client._load_payload_bytes("missing")

    monkeypatch.setattr(
        client_mod,
        "load_virtual_payload",
        lambda _dsn, _id: '{"custom_id":"r1"}\n',
    )
    client._session = FakeSession(
        {("POST", "/files"): FakeResponse(400, {"error": "bad payload"})}
    )
    with pytest.raises(GatewayError) as exc_info:
        await client.upload_jsonl("memory://bad", "default")
    assert exc_info.value.status_code == 400
    assert exc_info.value.response_data == {"error": "bad payload"}


async def test_create_status_download_and_cancel_error_paths():
    client = BatchAPIClient("postgresql://x", _creds)
    client._session = FakeSession(
        {("POST", "/batches"): FakeResponse(503, {"error": "unavailable"})}
    )
    with pytest.raises(GatewayError) as exc_info:
        await client.create_batch_job("file", "default", metadata={"tenant": "a"})
    assert exc_info.value.status_code == 503

    client._session = FakeSession(
        {
            ("GET", "/batches/bad-status"): FakeResponse(502, {"error": "gateway"}),
            ("GET", "/batches/no-output"): FakeResponse(
                200, {"status": "completed", "request_counts": {}}
            ),
            ("GET", "/batches/download-error"): FakeResponse(
                200,
                {
                    "status": "completed",
                    "output_file_id": "out-bad",
                    "request_counts": {"total": 0},
                },
            ),
            ("GET", "/files/out-bad/content"): FakeResponse(500, text="storage down"),
            ("POST", "/batches/cancel-fail/cancel"): FakeResponse(
                409, {"error": {"message": "already complete"}}
            ),
            ("POST", "/batches/cancel-unknown/cancel"): FakeResponse(500, {}),
            ("POST", "/batches/cancel-ok/cancel"): FakeResponse(
                202, {"status": "cancelling"}
            ),
            ("POST", "/batches/cancel-default/cancel"): FakeResponse(200, {}),
        }
    )

    with pytest.raises(GatewayError, match="Batch status failed"):
        await client.get_batch_status("bad-status", "default")
    no_output = await client.download_results("no-output", "default")
    assert no_output == {"success": False, "reason": "No output_file_id on batch"}
    with pytest.raises(GatewayError) as exc_info:
        await client.download_results("download-error", "default")
    assert exc_info.value.response_data == {"body": "storage down"}

    assert await client.cancel_batch("cancel-fail", "default") == {
        "success": False,
        "reason": "already complete",
    }
    assert (await client.cancel_batch("cancel-unknown", "default"))["reason"] == (
        "Unknown error"
    )
    assert await client.cancel_batch("cancel-ok", "default") == {
        "success": True,
        "batch_id": "cancel-ok",
        "status": "cancelling",
    }
    assert (await client.cancel_batch("cancel-default", "default"))["status"] == (
        "cancelling"
    )


async def test_terminal_status_and_metadata_success():
    session = FakeSession(
        {
            ("POST", "/batches"): FakeResponse(202, {"id": "batch"}),
            ("GET", "/batches/failed"): FakeResponse(
                200,
                {
                    "status": "failed",
                    "request_counts": {"total": 0, "completed": 0, "failed": 0},
                },
            ),
        }
    )
    client = BatchAPIClient("postgresql://x", _creds)
    client._session = session
    assert (
        await client.create_batch_job(
            "file", "default", metadata={"trace_id": "trace-1"}
        )
    )["id"] == "batch"
    post = next(call for call in session.calls if call[0] == "POST")
    assert post[2]["json"]["metadata"] == {"trace_id": "trace-1"}
    status = await client.get_batch_status("failed", "default")
    assert status["is_complete"] is True
    assert status["progress_percentage"] == 0
