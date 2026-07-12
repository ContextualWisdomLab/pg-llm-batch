# SPDX-License-Identifier: Apache-2.0
"""Unit tests for readiness aggregation and explicit failure evidence."""

from __future__ import annotations

import io

from pg_llm_batch import health


class _Cursor:
    """Return a fixed set of health-check rows."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def execute(self, _sql):
        return None

    def fetchall(self):
        return list(self._rows)


class _Connection:
    """Minimal context-managed connection for health checks."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def cursor(self):
        return _Cursor(self._rows)


class _Psycopg:
    """Minimal psycopg facade returning fixed health rows."""

    def __init__(self, rows):
        self._rows = rows

    def connect(self, _dsn, *, connect_timeout):
        assert connect_timeout == 5
        return _Connection(self._rows)


def test_missing_required_component_is_reported_not_ready(monkeypatch):
    """A partial health function result must never pass by vacuous truth."""
    monkeypatch.setattr(
        health,
        "psycopg",
        _Psycopg([("database", True, "connected")]),
    )

    report = health.check_health("postgresql://example")

    assert report["ready"] is False
    missing = {
        item["component"]: item["detail"]
        for item in report["components"]
        if not item["is_ready"]
    }
    assert missing == {
        "com_config": "missing from pg_llm_batch_health_check() result",
        "pg_tiktoken": "missing from pg_llm_batch_health_check() result",
    }


def test_health_dependency_and_database_failures_include_reason(monkeypatch):
    """Dependency and connection failures are explicit rather than hidden."""
    monkeypatch.setattr(health, "psycopg", None)
    report = health.check_health("postgresql://example")
    assert report == {
        "ready": False,
        "components": [
            {"component": "psycopg", "is_ready": False, "detail": "not installed"}
        ],
    }

    class BrokenPsycopg:
        @staticmethod
        def connect(_dsn, *, connect_timeout):
            raise OSError(f"connection refused after {connect_timeout}s")

    monkeypatch.setattr(health, "psycopg", BrokenPsycopg())
    report = health.check_health("postgresql://example")
    assert report["ready"] is False
    assert "connection refused after 5s" in report["components"][0]["detail"]


def test_health_requires_every_required_component(monkeypatch):
    """Optional failures do not mask readiness, while required failures do."""
    rows = [
        ("database", True, "connected"),
        ("pg_tiktoken", True, "installed"),
        ("com_config", True, "ready"),
        ("optional_metrics", False, "disabled"),
    ]
    monkeypatch.setattr(health, "psycopg", _Psycopg(rows))
    assert health.check_health("postgresql://example")["ready"] is True

    rows[1] = ("pg_tiktoken", False, "extension unavailable")
    monkeypatch.setattr(health, "psycopg", _Psycopg(rows))
    assert health.check_health("postgresql://example")["ready"] is False


def test_serve_healthz_reports_status_body_and_not_found(monkeypatch):
    """The HTTP wrapper emits JSON readiness and a strict 404 elsewhere."""
    events = []

    class FakeHTTPServer:
        def __init__(self, address, handler_class):
            events.append(("address", address))
            self.handler_class = handler_class

        def _request(self, path):
            handler = self.handler_class.__new__(self.handler_class)
            handler.path = path
            handler.wfile = io.BytesIO()
            handler.send_response = lambda status: events.append((path, "status", status))
            handler.send_header = lambda key, value: events.append(
                (path, "header", key, value)
            )
            handler.end_headers = lambda: events.append((path, "headers-ended"))
            handler.do_GET()
            return handler.wfile.getvalue()

        def serve_forever(self):
            assert self._request("/other") == b""
            body = self._request("/healthz/")
            assert b'"ready": false' in body
            handler = self.handler_class.__new__(self.handler_class)
            assert handler.log_message("ignored") is None

    monkeypatch.setattr("http.server.HTTPServer", FakeHTTPServer)
    monkeypatch.setattr(
        health,
        "check_health",
        lambda _dsn: {"ready": False, "components": []},
    )
    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)
    assert ("address", ("127.0.0.1", 8090)) in events
    assert ("/other", "status", 404) in events
    assert ("/healthz/", "status", 503) in events
    assert ("/healthz/", "header", "Content-Type", "application/json") in events
