"""Regression tests for bounded GitHub API response reads in the audit tool."""

from __future__ import annotations

import traceback

import aiohttp
import pytest

from pg_llm_batch.workflow_registry_audit import GitHubReadClient, WorkflowRegistryAuditError


class _Content:
    """Expose deterministic response chunks through aiohttp's streaming shape."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        """Yield the configured chunks without buffering them into one body first."""
        for chunk in self._chunks:
            yield chunk


class _Response:
    """Represent one successful GitHub response with controllable body metadata."""

    status = 200
    headers: dict[str, str] = {}

    def __init__(self, body: bytes, *, content_length: int | None) -> None:
        self._body = body
        self.content_length = content_length
        self.content = _Content(body)

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def read(self) -> bytes:
        """Model the unsafe whole-body path that the production client must avoid."""
        return self._body


class _Session:
    """Return exactly one prepared response from the fixed-origin client session."""

    response: _Response

    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> None:
        assert base_url == "https://api.github.com"
        assert headers["Accept"] == "application/vnd.github+json"
        assert timeout.total == 15.0

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, _path: str, *, allow_redirects: bool) -> _Response:
        assert allow_redirects is False
        return self.response


def test_declared_oversize_response_fails_before_whole_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared oversized response must fail before materializing its body."""
    _Session.response = _Response(b"{}", content_length=32 * 1024 * 1024)
    monkeypatch.setattr("pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession", _Session)
    client = GitHubReadClient(token="bounded-token")

    with pytest.raises(WorkflowRegistryAuditError, match="response exceeded byte limit"):
        client.get_json("/repos/ContextualWisdomLab/pg-llm-batch/actions/workflows")


def test_chunked_oversize_response_fails_with_bounded_nonsecret_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chunked responses without Content-Length cannot bypass the body budget."""
    secret_sentinel = "SECRET_RESPONSE_BODY_MUST_NOT_ESCAPE"
    body = ('{"value":"' + secret_sentinel + '"}').encode()
    _Session.response = _Response(body, content_length=None)
    monkeypatch.setattr("pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession", _Session)
    monkeypatch.setattr("pg_llm_batch.workflow_registry_audit._MAX_RESPONSE_BYTES", 8, raising=False)
    client = GitHubReadClient(token="bounded-token")

    try:
        client.get_json("/repos/ContextualWisdomLab/pg-llm-batch/actions/workflows")
    except WorkflowRegistryAuditError as exc:
        rendered = "".join(traceback.format_exception(exc))
        assert str(exc) == "GitHub workflow audit response exceeded byte limit"
        assert secret_sentinel not in rendered
        assert "bounded-token" not in rendered
        assert exc.__cause__ is None
    else:
        raise AssertionError("expected WorkflowRegistryAuditError")


def test_recursive_json_decoder_failure_is_normalized_without_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recursion-limited JSON decoder failure remains a fixed audit error."""
    secret_sentinel = "SECRET_RECURSION_DIAGNOSTIC_MUST_NOT_ESCAPE"
    _Session.response = _Response(b"{}", content_length=2)
    monkeypatch.setattr("pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession", _Session)

    def _raise_recursion(_content: str) -> object:
        raise RecursionError(secret_sentinel)

    monkeypatch.setattr("pg_llm_batch.workflow_registry_audit.json.loads", _raise_recursion)
    client = GitHubReadClient(token="bounded-token")

    try:
        client.get_json("/repos/ContextualWisdomLab/pg-llm-batch/actions/workflows")
    except WorkflowRegistryAuditError as exc:
        rendered = "".join(traceback.format_exception(exc))
        assert str(exc) == "GitHub workflow audit read failed"
        assert secret_sentinel not in rendered
        assert "bounded-token" not in rendered
        assert exc.__cause__ is None
        assert exc.__suppress_context__ is True
    else:
        raise AssertionError("expected WorkflowRegistryAuditError")
