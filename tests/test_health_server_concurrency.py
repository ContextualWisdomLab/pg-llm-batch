# SPDX-License-Identifier: Apache-2.0
"""Regression tests for concurrent standalone readiness serving."""

from __future__ import annotations

from socketserver import ThreadingMixIn
from typing import Any

from pg_llm_batch import health


class _HTTPServer:
    """Record whether the selected server applies threaded request handling."""

    concurrent: list[bool] = []

    def __init__(self, _address: tuple[str, int], _handler_class: type[Any]) -> None:
        """Record whether the instantiated server includes ``ThreadingMixIn``."""
        self.concurrent.append(isinstance(self, ThreadingMixIn))

    def serve_forever(self) -> None:
        """Return immediately instead of entering a real server loop."""


def test_health_server_does_not_serialize_independent_probe_requests(
    monkeypatch: Any,
) -> None:
    """A blocked readiness check must not prevent another probe from starting."""
    selections: list[bool] = []
    _HTTPServer.concurrent = selections
    monkeypatch.setattr("http.server.HTTPServer", _HTTPServer)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    assert selections == [True]
