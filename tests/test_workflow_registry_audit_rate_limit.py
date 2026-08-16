"""Rate-limit classification regressions for the workflow registry audit."""

from __future__ import annotations

import aiohttp
import pytest

from pg_llm_batch.workflow_registry_audit import GitHubReadClient, WorkflowRegistryAuditError


REPOSITORY = "ContextualWisdomLab/pg-llm-batch"


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (429, {}),
        (403, {"X-RateLimit-Remaining": "0"}),
        (403, {"Retry-After": "60"}),
    ],
)
def test_rate_limit_responses_have_bounded_distinct_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    headers: dict[str, str],
) -> None:
    """Known GitHub rate-limit signals must not be conflated with generic failure."""

    class _Response:
        async def __aenter__(self) -> "_Response":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def read(self) -> bytes:
            raise AssertionError("rate-limit response bodies must not be rendered or parsed")

    response = _Response()
    response.status = status
    response.headers = headers

    class _Session:
        def __init__(
            self,
            *,
            base_url: str,
            headers: dict[str, str],
            timeout: aiohttp.ClientTimeout,
        ) -> None:
            assert base_url == "https://api.github.com"
            assert timeout.total == 15.0

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def get(self, _path: str, *, allow_redirects: bool) -> _Response:
            assert allow_redirects is False
            return response

    monkeypatch.setattr("pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession", _Session)
    client = GitHubReadClient(token="bounded-test-token")

    with pytest.raises(WorkflowRegistryAuditError, match="^GitHub workflow audit rate limited$"):
        client.get_json(f"/repos/{REPOSITORY}/actions/workflows?per_page=100&page=1")


def test_ordinary_forbidden_response_remains_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 without a rate-limit signal must remain an authorization-agnostic failure."""

    class _Response:
        status = 403
        headers: dict[str, str] = {}

        async def __aenter__(self) -> "_Response":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def read(self) -> bytes:
            raise AssertionError("non-success response bodies must not be rendered or parsed")

    class _Session:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def get(self, _path: str, *, allow_redirects: bool) -> _Response:
            assert allow_redirects is False
            return _Response()

    monkeypatch.setattr("pg_llm_batch.workflow_registry_audit.aiohttp.ClientSession", _Session)
    client = GitHubReadClient(token="bounded-test-token")

    with pytest.raises(WorkflowRegistryAuditError, match="^GitHub workflow audit read failed$"):
        client.get_json(f"/repos/{REPOSITORY}/actions/workflows?per_page=100&page=1")
