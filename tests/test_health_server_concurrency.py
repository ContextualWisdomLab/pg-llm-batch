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


def test_health_server_saturation_does_not_amplify_logs(monkeypatch: Any) -> None:
    """Refused probe connections must not create attacker-controlled log volume."""
    started: list[object] = []
    rejected: list[object] = []
    warnings: list[tuple[object, ...]] = []

    class _SaturatedHTTPServer:
        """Hold one worker slot while offering one excess connection."""

        def __init__(
            self,
            _address: tuple[str, int],
            _handler_class: type[Any],
        ) -> None:
            """Create the deterministic server double without opening a socket."""

        def serve_forever(self) -> None:
            """Offer two requests to a one-slot server without completing the first."""
            for index in range(2):
                self.process_request(object(), ("127.0.0.1", 10_500 + index))

        def shutdown_request(self, request: object) -> None:
            """Record the expected excess-connection refusal."""
            rejected.append(request)

    def record_thread_start(
        _server: Any,
        request: object,
        _client_address: tuple[str, int],
    ) -> None:
        """Hold the admitted slot without allocating a real thread."""
        started.append(request)

    def record_warning(*args: object, **_kwargs: object) -> None:
        """Capture any per-refusal warning emitted by the listener."""
        warnings.append(args)

    monkeypatch.setattr(health, "HEALTH_MAX_CONCURRENT_REQUESTS", 1)
    monkeypatch.setattr("http.server.HTTPServer", _SaturatedHTTPServer)
    monkeypatch.setattr(ThreadingMixIn, "process_request", record_thread_start)
    monkeypatch.setattr(health.logger, "warning", record_warning)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    assert len(started) == 1
    assert len(rejected) == 1
    assert warnings == []


def test_health_server_releases_admission_slot_when_thread_start_fails(
    monkeypatch: Any,
) -> None:
    """A failed thread allocation cannot permanently consume an admission slot."""
    starts: list[object] = []
    rejected: list[object] = []

    class _ThreadStartFailureHTTPServer:
        """Attempt two requests while catching simulated thread-start failures."""

        def __init__(
            self,
            _address: tuple[str, int],
            _handler_class: type[Any],
        ) -> None:
            """Create the deterministic server double without opening a socket."""

        def serve_forever(self) -> None:
            """Try two requests so the second proves the first slot was released."""
            for index in range(2):
                try:
                    self.process_request(object(), ("127.0.0.1", 11_000 + index))
                except RuntimeError as exc:
                    assert str(exc) == "thread-start-failed"

        def shutdown_request(self, request: object) -> None:
            """Record an admission refusal caused by a leaked worker slot."""
            rejected.append(request)

    def fail_thread_start(
        _server: Any,
        request: object,
        _client_address: tuple[str, int],
    ) -> None:
        """Record the attempt and emulate failure before a worker thread exists."""
        starts.append(request)
        raise RuntimeError("thread-start-failed")

    monkeypatch.setattr(health, "HEALTH_MAX_CONCURRENT_REQUESTS", 1)
    monkeypatch.setattr("http.server.HTTPServer", _ThreadStartFailureHTTPServer)
    monkeypatch.setattr(ThreadingMixIn, "process_request", fail_thread_start)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    assert len(starts) == 2
    assert rejected == []


def test_health_server_releases_admission_slot_after_request_completion(
    monkeypatch: Any,
) -> None:
    """A completed request returns its slot so the next probe can be admitted."""
    handled: list[object] = []
    rejected: list[object] = []

    class _SynchronousHTTPServer:
        """Drive two sequential requests through the production thread-finalizer."""

        def __init__(
            self,
            _address: tuple[str, int],
            _handler_class: type[Any],
        ) -> None:
            """Create the deterministic server double without opening a socket."""

        def serve_forever(self) -> None:
            """Offer two requests to a one-slot server in sequence."""
            for index in range(2):
                self.process_request(object(), ("127.0.0.1", 12_000 + index))

        def shutdown_request(self, request: object) -> None:
            """Record an unexpected refusal after a completed request."""
            rejected.append(request)

    def run_request_synchronously(
        server: Any,
        request: object,
        client_address: tuple[str, int],
    ) -> None:
        """Invoke the production thread finalizer without creating a real thread."""
        server.process_request_thread(request, client_address)

    def record_request(
        _server: Any,
        request: object,
        _client_address: tuple[str, int],
    ) -> None:
        """Record a completed base request-thread body."""
        handled.append(request)

    monkeypatch.setattr(health, "HEALTH_MAX_CONCURRENT_REQUESTS", 1)
    monkeypatch.setattr("http.server.HTTPServer", _SynchronousHTTPServer)
    monkeypatch.setattr(ThreadingMixIn, "process_request", run_request_synchronously)
    monkeypatch.setattr(ThreadingMixIn, "process_request_thread", record_request)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    assert len(handled) == 2
    assert rejected == []


def test_health_handler_bounds_partial_request_read_time(monkeypatch: Any) -> None:
    """Each admitted socket must have a finite read timeout against slow clients."""
    handler_classes: list[type[Any]] = []

    class _CapturingHTTPServer:
        """Capture the request handler contract without opening a real socket."""

        def __init__(
            self,
            _address: tuple[str, int],
            handler_class: type[Any],
        ) -> None:
            """Retain the generated handler class for timeout inspection."""
            handler_classes.append(handler_class)

        def serve_forever(self) -> None:
            """Return immediately instead of entering a real server loop."""

    monkeypatch.setattr("http.server.HTTPServer", _CapturingHTTPServer)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    assert len(handler_classes) == 1
    assert handler_classes[0].timeout == health.HEALTH_REQUEST_TIMEOUT_SECONDS
