# SPDX-License-Identifier: Apache-2.0
"""Fail-first contracts for exact gateway URL authority."""

import pytest

from pg_llm_batch.batch_api_client import config_credentials_provider
from pg_llm_batch.exceptions import GatewayError


class _ConfigStore:
    """Return one caller-selected gateway value without altering its type or bytes."""

    def __init__(self, value):
        self.value = value

    def get(self, category, key, default):
        assert category == "gateway"
        return self.value


class _SecretStore:
    """Record whether URL validation leaked into credential acquisition."""

    def __init__(self):
        self.called = False

    def require_secret(self, key):
        self.called = True
        return "sk-test"


@pytest.mark.parametrize(
    "gateway_url",
    (
        " https://gw.example/v1",
        "https://gw.example/v1 ",
        "https://gw.example/v1\x7f",
    ),
)
def test_gateway_url_rejects_non_exact_whitespace_or_del_before_secret_lookup(gateway_url):
    """Unsafe normalization must fail before a provider credential is acquired."""
    secrets = _SecretStore()
    provider = config_credentials_provider(_ConfigStore(gateway_url), secrets)

    with pytest.raises(GatewayError, match="Gateway base_url"):
        provider("default")

    assert secrets.called is False


def test_gateway_url_rejects_stringifiable_non_string_before_secret_lookup():
    """A caller-controlled object must not gain URL authority through ``str`` coercion."""

    class StringifiableURL:
        def __str__(self):
            return "https://gw.example/v1"

    secrets = _SecretStore()
    provider = config_credentials_provider(_ConfigStore(StringifiableURL()), secrets)

    with pytest.raises(GatewayError, match="Gateway base_url"):
        provider("default")

    assert secrets.called is False
