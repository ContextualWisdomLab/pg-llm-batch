# SPDX-License-Identifier: Apache-2.0
"""Privacy and authority regressions for endpoint-alias credential resolution."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import (
    BatchAPIClient,
    GatewayCredentials,
    config_credentials_provider,
)
from pg_llm_batch.db import MAX_ENDPOINT_ALIAS_CHARACTERS
from pg_llm_batch.exceptions import GatewayError, ValidationError


class _ConfigStore:
    """Record configuration lookups without granting any fallback behavior."""

    def __init__(self, values: dict[tuple[str, str], Any] | None = None) -> None:
        self.values = values or {}
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, category: str, key: str, default: Any) -> Any:
        """Return one configured value while preserving the exact lookup key."""
        self.calls.append((category, key, default))
        return self.values.get((category, key), default)


class _SecretStore:
    """Record secret-key lookups and return one deterministic test credential."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def require_secret(self, key: str) -> str:
        """Return a fixed secret after recording only the requested key."""
        self.calls.append(key)
        return "test-secret"


@pytest.mark.parametrize(
    "alias",
    [
        "bad/alias",
        "bad alias",
        "한글",
        "bad\nalias",
        "a" * (MAX_ENDPOINT_ALIAS_CHARACTERS + 1),
    ],
)
def test_config_provider_rejects_noncanonical_alias_before_store_access(
    alias: str,
) -> None:
    """Reject aliases outside the bounded ASCII grammar before any store can observe them."""
    config = _ConfigStore()
    secrets = _SecretStore()
    provider = config_credentials_provider(config, secrets)

    with pytest.raises(ValidationError) as raised:
        provider(alias)

    assert alias not in str(raised.value)
    assert raised.value.details["value"] == "<redacted>"
    assert config.calls == []
    assert secrets.calls == []


async def test_batch_client_rejects_alias_before_custom_credential_resolution() -> None:
    """Invalid aliases must fail before an injected credential provider can observe them."""
    credential_calls: list[str] = []

    def _credentials(alias: str) -> GatewayCredentials:
        credential_calls.append(alias)
        raise AssertionError("credential provider must not receive an invalid alias")

    client = BatchAPIClient("postgresql://test", _credentials)

    with pytest.raises(ValidationError):
        await client.get_batch_status("batch-1", "operator/secret")

    assert credential_calls == []


def test_config_credentials_provider_uses_normalized_alias_for_all_store_keys() -> None:
    """Whitespace normalization must happen once before configuration or secret lookup."""
    config = _ConfigStore(
        {("gateway", "default"): "https://gateway.example.test/v1"}
    )
    secrets = _SecretStore()
    provider = config_credentials_provider(config, secrets)

    credentials = provider(" default ")

    assert credentials.url == "https://gateway.example.test/v1"
    assert credentials.api_key == "test-secret"
    assert config.calls == [("gateway", "default", None)]
    assert secrets.calls == ["gateway_api_key.default"]


def test_missing_gateway_configuration_does_not_echo_valid_alias() -> None:
    """Missing configuration diagnostics must not turn an alias into loggable content."""
    config = _ConfigStore()
    secrets = _SecretStore()
    provider = config_credentials_provider(config, secrets)
    alias = "private-admin"

    with pytest.raises(GatewayError) as raised:
        provider(alias)

    assert alias not in str(raised.value)
    assert config.calls == [
        ("gateway", alias, None),
        ("gateway", "base_url", None),
    ]
    assert secrets.calls == []
