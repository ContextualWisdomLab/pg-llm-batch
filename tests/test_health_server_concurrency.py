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


def test_health_server_bounds_concurrent_probe_threads(monkeypatch: Any) -> None:
    """A connection flood cannot allocate an unbounded number of probe threads."""
    started: list[object] = []
    rejected: list[object] = []

    class _AdmissionHTTPServer:
        """Drive 33 accepted connections without completing any started request."""

        def __init__(
            self,
            _address: tuple[str, int],
            _handler_class: type[Any],
        ) -> None:
            """Create the deterministic server double without opening a socket."""

        def serve_forever(self) -> None:
            """Offer one more connection than the reviewed 32-request ceiling."""
            for index in range(33):
                self.process_request(object(), ("127.0.0.1", 10_000 + index))

        def shutdown_request(self, request: object) -> None:
            """Record a refused connection without allocating another thread."""
            rejected.append(request)

    def record_thread_start(
        _server: Any,
        request: object,
        _client_address: tuple[str, int],
    ) -> None:
        """Record a thread allocation without starting a real test thread."""
        started.append(request)

    monkeypatch.setattr("http.server.HTTPServer", _AdmissionHTTPServer)
    monkeypatch.setattr(ThreadingMixIn, "process_request", record_thread_start)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    assert len(started) == 32
    assert len(rejected) == 1
