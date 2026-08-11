# SPDX-License-Identifier: Apache-2.0
"""Regression tests for confidential GatewayCredentials representations."""

from pg_llm_batch.batch_api_client import GatewayCredentials


def test_gateway_credentials_representation_excludes_api_key() -> None:
    """Keep provider API keys out of repr/str while retaining useful identity."""
    secret = "credential-sentinel-128-never-render"
    credentials = GatewayCredentials(url="https://gateway.example.test", api_key=secret)

    rendered_repr = repr(credentials)
    rendered_str = str(credentials)

    assert secret not in rendered_repr
    assert secret not in rendered_str
    assert "GatewayCredentials" in rendered_repr
    assert "https://gateway.example.test" in rendered_repr
    assert credentials.api_key == secret
    assert credentials == GatewayCredentials(
        url="https://gateway.example.test", api_key=secret
    )
