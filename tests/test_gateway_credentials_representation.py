# SPDX-License-Identifier: Apache-2.0
"""Regression tests for confidential GatewayCredentials representations."""

from pg_llm_batch.batch_api_client import GatewayCredentials


def test_gateway_credentials_representation_excludes_api_key() -> None:
    """Keep provider API keys out of repr/str while retaining useful identity."""
    secret = "credential-sentinel-128-never-render"
    gateway_url = "https://gateway.example.test"
    credentials = GatewayCredentials(url=gateway_url, api_key=secret)

    rendered_repr = repr(credentials)
    rendered_str = str(credentials)

    assert secret not in rendered_repr
    assert secret not in rendered_str
    assert "api_key=" not in rendered_repr
    assert rendered_repr.startswith("GatewayCredentials(")
    assert credentials.url == gateway_url
    assert credentials.api_key == secret
    assert credentials == GatewayCredentials(url=gateway_url, api_key=secret)
