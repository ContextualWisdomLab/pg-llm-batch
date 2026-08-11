# SPDX-License-Identifier: Apache-2.0
"""Regression tests for fail-closed provider transport retry classification."""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


@dataclass(frozen=True)
class _ConnectionKey:
    """Provide the aiohttp connection-key fields used by TLS exceptions."""

    host: str = "gateway.example"
    port: int = 443
    ssl: bool = True


class _Response:
    """Minimal successful asynchronous response context."""

    status = 200
    headers: dict[str, str] = {}

    async def __aenter__(self) -> "_Response":
        """Return this response when the request context is entered."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Release the response context without side effects."""


class _FailureContext:
    """Raise one configured transport exception during request acquisition."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def __aenter__(self) -> Any:
        """Raise the configured failure before any response is handed off."""
        raise self.error

    async def __aexit__(self, *_exc: Any) -> None:
        """Provide the asynchronous context-manager protocol for the fake."""


class _SequenceSession:
    """Return configured response contexts while recording GET attempts."""

    def __init__(self, entries: list[Any]) -> None:
        self.entries = list(entries)
        self.calls = 0

    def get(self, _url: str, **_kwargs: Any) -> Any:
        """Return the next response context or transport-failure context."""
        self.calls += 1
        if not self.entries:
            raise AssertionError("no request result left")
        entry = self.entries.pop(0)
        if isinstance(entry, BaseException):
            return _FailureContext(entry)
        return entry


class ProviderNamedClientFailure(aiohttp.ClientError):
    """Model a dependency-defined exception class whose name is untrusted."""


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials without touching external services."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def _tls_failures() -> list[aiohttp.ClientSSLError]:
    """Build permanent TLS failures using aiohttp's public exception classes."""
    key = _ConnectionKey()
    return [
        aiohttp.ClientConnectorSSLError(key, ssl.SSLError("tls-handshake-failed")),
        aiohttp.ClientConnectorCertificateError(
            key,
            ssl.CertificateError("certificate-verification-failed"),
        ),
    ]


@pytest.mark.parametrize("tls_failure", _tls_failures())
async def test_permanent_tls_failures_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    tls_failure: aiohttp.ClientSSLError,
) -> None:
    """TLS failures fail once without exporting the provider exception chain."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    session = _SequenceSession([tls_failure, _Response(), _Response()])
    client = BatchAPIClient("postgresql://example", _credentials)
    client._session = session

    with pytest.raises(GatewayError, match="Batch status transport failed") as caught:
        async with client._request(
            "get",
            "https://gateway.example/v1/batches/batch-1",
            operation="Batch status",
        ):
            pytest.fail("a TLS failure must not hand off a response")

    expected_error_type = (
        "ClientConnectorCertificateError"
        if isinstance(tls_failure, aiohttp.ClientConnectorCertificateError)
        else "ClientSSLError"
    )
    assert caught.value.response_data == {
        "error_type": expected_error_type,
        "timeout_seconds": client.request_timeout_seconds,
    }
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    for sensitive_detail in (
        "gateway.example",
        "tls-handshake-failed",
        "certificate-verification-failed",
    ):
        assert sensitive_detail not in str(caught.value)
    assert session.calls == 1
    assert sleeps == []


async def test_server_fingerprint_mismatch_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Certificate fingerprint mismatches are permanent peer-identity failures."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    fingerprint_failure = aiohttp.ServerFingerprintMismatch(
        b"expected-fingerprint",
        b"received-fingerprint",
        "gateway.example",
        443,
    )
    session = _SequenceSession([fingerprint_failure, _Response(), _Response()])
    client = BatchAPIClient("postgresql://example", _credentials)
    client._session = session

    with pytest.raises(GatewayError, match="Batch status transport failed") as caught:
        async with client._request(
            "get",
            "https://gateway.example/v1/batches/batch-1",
            operation="Batch status",
        ):
            pytest.fail("a fingerprint mismatch must not hand off a response")

    assert caught.value.response_data == {
        "error_type": "ServerFingerprintMismatch",
        "timeout_seconds": client.request_timeout_seconds,
    }
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    for sensitive_detail in (
        "gateway.example",
        "expected-fingerprint",
        "received-fingerprint",
    ):
        assert sensitive_detail not in str(caught.value)
    assert session.calls == 1
    assert sleeps == []


async def test_dependency_defined_client_error_uses_bounded_error_type(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Provider-defined class names must not enter diagnostics or retry logs."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    failure = ProviderNamedClientFailure("gateway.example sensitive-provider-detail")
    session = _SequenceSession([failure, failure])
    client = BatchAPIClient(
        "postgresql://example",
        _credentials,
        max_retry_attempts=2,
    )
    client._session = session

    with pytest.raises(GatewayError, match="Batch status transport failed") as caught:
        async with client._request(
            "get",
            "https://gateway.example/v1/batches/batch-1",
            operation="Batch status",
        ):
            pytest.fail("a transport failure must not hand off a response")

    assert caught.value.response_data == {
        "error_type": "ClientError",
        "timeout_seconds": client.request_timeout_seconds,
    }
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "ProviderNamedClientFailure" not in str(caught.value.response_data)
    assert "ProviderNamedClientFailure" not in caplog.text
    assert "gateway.example" not in str(caught.value)
    assert "sensitive-provider-detail" not in str(caught.value)
    assert session.calls == 2
    assert len(sleeps) == 1


async def test_timeout_remains_retryable_for_idempotent_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request-acquisition timeout still receives one bounded GET retry."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    session = _SequenceSession([asyncio.TimeoutError(), _Response()])
    client = BatchAPIClient("postgresql://example", _credentials)
    client._session = session

    async with client._request(
        "get",
        "https://gateway.example/v1/batches/batch-1",
        operation="Batch status",
    ) as response:
        assert response.status == 200

    assert session.calls == 2
    assert sleeps == [0.5]


def test_authoritative_docs_define_tls_fail_closed_retry_boundary() -> None:
    """Public and operator contracts must document every permanent TLS failure class."""
    required_phrases = (
        "TLS handshake and certificate failures are never retried automatically",
        "Certificate fingerprint mismatches are never retried automatically",
    )
    authoritative_paths = (
        "README.md",
        "AGENTS.md",
        "CHANGELOG.md",
        "docs/adr/0015-http-425-too-early-retry.md",
        "docs/doctoring/http-425-too-early-retries.md",
    )

    for path in authoritative_paths:
        normalized = " ".join(Path(path).read_text(encoding="utf-8").split())
        for required_phrase in required_phrases:
            assert required_phrase in normalized, path


def test_authoritative_docs_define_bounded_transport_error_vocabulary() -> None:
    """Operator contracts must exclude dependency-defined class names from evidence."""
    required_phrase = "Dependency-defined transport exception class names never enter"
    for path in (
        "CHANGELOG.md",
        "docs/doctoring/http-425-too-early-retries.md",
    ):
        normalized = " ".join(Path(path).read_text(encoding="utf-8").split())
        assert required_phrase in normalized, path
