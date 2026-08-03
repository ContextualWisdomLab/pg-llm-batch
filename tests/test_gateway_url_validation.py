# SPDX-License-Identifier: Apache-2.0
"""Security tests for credential-bearing gateway destinations."""

from __future__ import annotations

import pytest

from pg_llm_batch.batch_api_client import (
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


def test_credentials_provider_normalizes_https_and_allows_loopback_http():
    """Production URLs require HTTPS while explicit local development remains usable."""
    secure_secrets = Secrets()
    secure = config_credentials_provider(
        Config(" https://api.example/v1/ "), secure_secrets
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
