# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded retries of idempotent provider GET requests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import aiohttp
import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


class Response:
    """Minimal asynchronous JSON response with optional retry guidance."""

    def __init__(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.payload = payload
        self.headers = headers or {}
        self.exit_count = 0

    async def __aenter__(self):
        """Enter the response context."""
        return self

    async def __aexit__(self, *_exc: Any):
        """Record response-context release."""
        self.exit_count += 1
        return None

    async def json(self) -> dict[str, Any]:
        """Return the configured JSON object."""
        return self.payload


class SequenceSession:
    """Return or raise an ordered sequence of request outcomes."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _next(self, method: str, url: str, kwargs: dict[str, Any]) -> Any:
        """Record a request and return or raise the next configured outcome."""
        self.calls.append((method, url, kwargs))
        if not self.outcomes:
            raise AssertionError(f"no outcome left for {method} {url}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def get(self, url: str, **kwargs: Any) -> Any:
        """Return the next GET outcome."""
        return self._next("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        """Return the next POST outcome."""
        return self._next("POST", url, kwargs)



def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic provider credentials."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "3", None])
def test_max_retry_attempts_requires_a_positive_integer(value: Any) -> None:
    """Retry attempts are finite positive non-boolean integers."""
    with pytest.raises(ValidationError, match="max_retry_attempts"):
        BatchAPIClient(
            "postgresql://x",
            credentials,
            max_retry_attempts=value,
        )


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("retry_base_delay_seconds", {"retry_base_delay_seconds": -1}),
        ("retry_base_delay_seconds", {"retry_base_delay_seconds": True}),
        ("retry_base_delay_seconds", {"retry_base_delay_seconds": float("inf")}),
        ("retry_base_delay_seconds", {"retry_base_delay_seconds": "0.5"}),
        ("retry_max_delay_seconds", {"retry_max_delay_seconds": -1}),
        ("retry_max_delay_seconds", {"retry_max_delay_seconds": True}),
        ("retry_max_delay_seconds", {"retry_max_delay_seconds": float("nan")}),
        ("retry_max_delay_seconds", {"retry_max_delay_seconds": None}),
        (
            "retry_base_delay_seconds",
            {"retry_base_delay_seconds": 2, "retry_max_delay_seconds": 1},
        ),
    ],
)
def test_retry_delays_require_finite_consistent_numbers(
    field: str,
    kwargs: dict[str, Any],
) -> None:
    """Retry delays are bounded finite numbers with base no larger than max."""
    with pytest.raises(ValidationError, match=field):
        BatchAPIClient("postgresql://x", credentials, **kwargs)


def test_retry_after_parser_accepts_delta_seconds_and_http_date() -> None:
    """RFC delta-seconds and HTTP-date forms produce non-negative delays."""
    now = datetime(2015, 10, 21, 7, 27, 30, tzinfo=timezone.utc)

    assert client_mod._parse_retry_after(" 2 ", now) == 2.0
    assert (
        client_mod._parse_retry_after(
            "Wed, 21 Oct 2015 07:28:00 GMT",
            now,
        )
        == 30.0
    )
    assert client_mod._parse_retry_after("Wed, 21 Oct 2015 07:27:00 GMT", now) == 0.0


@pytest.mark.parametrize("value", [None, True, "", "-1", "1.5", "not-a-date"])
def test_retry_after_parser_rejects_malformed_values(value: Any) -> None:
    """Malformed or non-string Retry-After values select fallback backoff."""
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    assert client_mod._parse_retry_after(value, now) is None


async def test_retryable_get_status_releases_response_then_succeeds(monkeypatch) -> None:
    """A transient GET status is released, delayed, and retried once."""
    sleeps: list[float] = []
    random_bounds: list[tuple[float, float]] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def choose_upper(lower: float, upper: float) -> float:
        random_bounds.append((lower, upper))
        return upper

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", choose_upper)
    first = Response(503, {"error": "busy"})
    session = SequenceSession(
        [
            first,
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    result = await client.get_batch_status("batch-1", "default")

    assert result["status"] == "completed"
    assert first.exit_count == 1
    assert sleeps == [0.5]
    assert random_bounds == [(0.25, 0.5)]
    assert [call[0] for call in session.calls] == ["GET", "GET"]


async def test_retry_after_delta_seconds_is_honored(monkeypatch) -> None:
    """A bounded Retry-After delta controls the retry delay exactly."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    session = SequenceSession(
        [
            Response(429, {"error": "rate-limited"}, headers={"Retry-After": "2"}),
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    result = await client.get_batch_status("batch-1", "default")

    assert result["status"] == "completed"
    assert sleeps == [2.0]


async def test_retry_after_http_date_uses_current_utc_time(monkeypatch) -> None:
    """An HTTP-date Retry-After is measured from the isolated UTC clock."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(
        client_mod,
        "_utc_now",
        lambda: datetime(2015, 10, 21, 7, 27, 30, tzinfo=timezone.utc),
    )
    session = SequenceSession(
        [
            Response(
                503,
                {"error": "maintenance"},
                headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
            ),
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    await client.get_batch_status("batch-1", "default")

    assert sleeps == [30.0]


async def test_excessive_retry_after_refuses_retry(monkeypatch) -> None:
    """An untrusted excessive wait cannot stall the client beyond its budget."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    session = SequenceSession(
        [Response(429, {"error": "rate-limited"}, headers={"Retry-After": "31"})]
    )
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        retry_max_delay_seconds=30,
    )
    client._session = session

    with pytest.raises(GatewayError, match="Batch status failed") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.status_code == 429
    assert sleeps == []
    assert len(session.calls) == 1


async def test_malformed_retry_after_uses_fallback(monkeypatch) -> None:
    """Malformed provider guidance falls back to bounded equal jitter."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    session = SequenceSession(
        [
            Response(503, {"error": "busy"}, headers={"Retry-After": "invalid"}),
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    await client.get_batch_status("batch-1", "default")

    assert sleeps == [0.5]


async def test_get_transport_failure_is_retried(monkeypatch) -> None:
    """A transient GET connection failure can recover within the attempt budget."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    session = SequenceSession(
        [
            aiohttp.ClientConnectionError("offline"),
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    result = await client.get_batch_status("batch-1", "default")

    assert result["status"] == "completed"
    assert sleeps == [0.5]
    assert len(session.calls) == 2


async def test_get_stops_after_maximum_attempts(monkeypatch) -> None:
    """Persistent retryable responses return the final provider failure."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    session = SequenceSession(
        [
            Response(503, {"error": "busy-1"}),
            Response(503, {"error": "busy-2"}),
            Response(503, {"error": "busy-3"}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials, max_retry_attempts=3)
    client._session = session

    with pytest.raises(GatewayError, match="Batch status failed") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.response_data == {"error": "busy-3"}
    assert sleeps == [0.5, 1.0]
    assert len(session.calls) == 3


async def test_post_status_is_not_retried(monkeypatch) -> None:
    """A side-effecting cancellation response remains single-attempt."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    session = SequenceSession(
        [Response(503, {"error": {"message": "busy"}})]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    result = await client.cancel_batch("batch-1", "default")

    assert result == {"success": False, "reason": "busy"}
    assert sleeps == []
    assert len(session.calls) == 1


async def test_post_transport_failure_is_not_retried(monkeypatch) -> None:
    """A POST transport ambiguity never replays a potentially applied operation."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    session = SequenceSession([asyncio.TimeoutError()])
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    with pytest.raises(GatewayError, match="Batch cancellation transport failed"):
        await client.cancel_batch("batch-1", "default")

    assert sleeps == []
    assert len(session.calls) == 1


def test_retry_after_parser_treats_naive_http_date_as_utc(monkeypatch) -> None:
    """A defensively parsed naive HTTP-date is interpreted as UTC."""
    monkeypatch.setattr(
        client_mod,
        "parsedate_to_datetime",
        lambda _value: datetime(2015, 10, 21, 7, 28, 0),
    )
    now = datetime(2015, 10, 21, 7, 27, 30, tzinfo=timezone.utc)
    assert client_mod._parse_retry_after("ignored", now) == 30.0


async def test_zero_fallback_delay_retries_without_random_jitter(monkeypatch) -> None:
    """A deliberate zero-delay policy retries without consulting randomness."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def fail_random(_lower: float, _upper: float) -> float:
        raise AssertionError("zero ceiling must not request jitter")

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", fail_random)
    session = SequenceSession(
        [
            Response(503, {"error": "busy"}),
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
    )
    client._session = session

    result = await client.get_batch_status("batch-1", "default")

    assert result["status"] == "completed"
    assert sleeps == [0.0]
