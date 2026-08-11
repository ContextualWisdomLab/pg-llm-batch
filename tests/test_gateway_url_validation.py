# SPDX-License-Identifier: Apache-2.0
"""Security tests for credential-bearing gateway destinations."""

from __future__ import annotations

import pytest

from pg_llm_batch.batch_api_client import (
    BatchAPIClient,
    GatewayCredentials,
    config_credentials_provider,
)
from pg_llm_batch.exceptions import GatewayError


class Config:
    """Return one configured gateway URL for every lookup."""

    def __init__(self, url):
        self.url = url

    def get(self, _category, _key, _default):
        return self.url


class Secrets:
    """Record whether a secret was resolved after URL validation."""

    def __init__(self):
        self.calls = []

    def require_secret(self, key):
        self.calls.append(key)
        return "secret"


class NeverRequestSession:
    """Fail if a rejected credential destination reaches HTTP acquisition."""

    def __init__(self):
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("unsafe credential destination reached HTTP")


def test_credentials_provider_normalizes_exact_https_and_allows_loopback_http():
    """Production URLs require exact HTTPS while explicit local development remains usable."""
    secure_secrets = Secrets()
    secure = config_credentials_provider(
        Config("https://api.example/v1/"), secure_secrets
    )("default")
    assert secure == GatewayCredentials(url="https://api.example/v1", api_key="secret")
    assert secure_secrets.calls == ["gateway_api_key.default"]

    for url in (
        "http://localhost:8000/v1/",
        "http://127.0.0.2:8000/v1",
        "http://[::1]:8000/v1",
    ):
        credentials = config_credentials_provider(Config(url), Secrets())("local")
        assert credentials.url == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example/v1",
        "ftp://api.example/v1",
        "https://user:password@api.example/v1",
        "https://api.example/v1?tenant=secret",
        "https://api.example/v1#fragment",
        "https:///missing-host",
        "https://api.example:99999/v1",
        "https://api.example:0/v1",
        "https://api.example/bad path",
        r"https://api.example\@evil.example/v1",
    ],
)
def test_credentials_provider_rejects_untrusted_destinations_before_secret_read(url):
    """Invalid or insecure destinations never receive a resolved API key."""
    secrets = Secrets()
    provider = config_credentials_provider(Config(url), secrets)

    with pytest.raises(GatewayError, match="Gateway base_url"):
        provider("default")

    assert secrets.calls == []


@pytest.mark.asyncio
async def test_client_revalidates_custom_credentials_destination_before_http():
    """Caller-supplied credential providers cannot bypass destination validation."""
    client = BatchAPIClient(
        "postgresql://unused",
        lambda _alias: GatewayCredentials(
            url="http://api.example/v1",
            api_key="secret-sentinel",
        ),
    )
    session = NeverRequestSession()
    client._session = session

    with pytest.raises(GatewayError, match="Gateway base_url"):
        await client.get_batch_status("batch-1", "default")

    assert session.calls == 0
