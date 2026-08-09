# SPDX-License-Identifier: Apache-2.0
"""Regression tests for concurrent standalone readiness serving."""

from __future__ import annotations

from typing import Any

from pg_llm_batch import health


class _SerialHTTPServer:
    """Record an unsafe serial-server selection without opening a socket."""

    selected: list[str] = []

    def __init__(self, _address: tuple[str, int], _handler_class: type[Any]) -> None:
        """Record that the serial server was selected."""
        self.selected.append("serial")

    def serve_forever(self) -> None:
        """Return immediately instead of entering a real server loop."""


class _ThreadingHTTPServer:
    """Record a concurrent-server selection without opening a socket."""

    selected: list[str] = []

    def __init__(self, _address: tuple[str, int], _handler_class: type[Any]) -> None:
        """Record that the concurrent server was selected."""
        self.selected.append("threading")

    def serve_forever(self) -> None:
        """Return immediately instead of entering a real server loop."""


def test_health_server_does_not_serialize_independent_probe_requests(
    monkeypatch: Any,
) -> None:
    """A blocked readiness check must not prevent another probe from starting."""
    selections: list[str] = []
    _SerialHTTPServer.selected = selections
    _ThreadingHTTPServer.selected = selections
    monkeypatch.setattr("http.server.HTTPServer", _SerialHTTPServer)
    monkeypatch.setattr("http.server.ThreadingHTTPServer", _ThreadingHTTPServer)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    assert selections == ["threading"]
