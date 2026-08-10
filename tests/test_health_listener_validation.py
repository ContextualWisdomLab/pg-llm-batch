# SPDX-License-Identifier: Apache-2.0
"""Fail-closed listener validation for the standalone readiness server."""

from __future__ import annotations

import http.server
from typing import Any

import pytest

from pg_llm_batch import health
from pg_llm_batch.exceptions import ValidationError


class _UnexpectedHTTPServer(http.server.HTTPServer):
    """Fail if an invalid listener reaches socket-server construction."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("invalid listener must fail before socket binding")


@pytest.mark.parametrize("host", ["", "   "])
def test_serve_healthz_rejects_blank_host_before_socket_binding(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    """Blank host input cannot become an implicit all-interface bind."""
    monkeypatch.setattr(http.server, "HTTPServer", _UnexpectedHTTPServer)

    with pytest.raises(ValidationError, match="host"):
        health.serve_healthz("postgresql://example", host=host, port=8080)


@pytest.mark.parametrize("host", [" 127.0.0.1", "127.0.0.1 ", "127.0.0.1\n", "local\x00host"])
def test_serve_healthz_rejects_malformed_host_text_before_socket_binding(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    """Whitespace-padded or NUL-bearing hosts fail at the package boundary."""
    monkeypatch.setattr(http.server, "HTTPServer", _UnexpectedHTTPServer)

    with pytest.raises(ValidationError, match="host"):
        health.serve_healthz("postgresql://example", host=host, port=8080)


@pytest.mark.parametrize("port", [True, 0, -1, 65536, 1.5, "8080"])
def test_serve_healthz_rejects_invalid_port_before_socket_binding(
    monkeypatch: pytest.MonkeyPatch,
    port: Any,
) -> None:
    """Only explicit integer TCP ports in the usable range may be bound."""
    monkeypatch.setattr(http.server, "HTTPServer", _UnexpectedHTTPServer)

    with pytest.raises(ValidationError, match="port"):
        health.serve_healthz("postgresql://example", host="127.0.0.1", port=port)
