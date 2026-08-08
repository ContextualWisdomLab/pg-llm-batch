# SPDX-License-Identifier: Apache-2.0
"""Unit tests for readiness aggregation and explicit failure evidence."""

from __future__ import annotations

import io
import json

from pg_llm_batch import health


class _Cursor:
    """Return fixed health-check rows while recording executed statements."""

    def __init__(self, rows, executions):
        self._rows = rows
        self._executions = executions

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def execute(self, sql, params=None):
        self._executions.append((sql, params))
        return None

    def fetchall(self):
        return list(self._rows)


class _Connection:
    """Minimal context-managed connection for health checks."""

    def __init__(self, rows, executions):
        self._rows = rows
        self._executions = executions

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def cursor(self):
        return _Cursor(self._rows, self._executions)


class _Psycopg:
    """Minimal psycopg facade returning fixed health rows."""

    def __init__(self, rows):
        self._rows = rows
        self.executions = []

    def connect(self, _dsn, *, connect_timeout):
        assert connect_timeout == 5
        return _Connection(self._rows, self.executions)


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
    """Local diagnostics retain dependency and connection failure reasons."""
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


def test_health_query_uses_transaction_local_statement_timeout(monkeypatch):
    """A stalled PostgreSQL health function cannot block readiness indefinitely."""
    rows = [
        ("database", True, "connected"),
        ("pg_tiktoken", True, "installed"),
        ("com_config", True, "ready"),
    ]
    database = _Psycopg(rows)
    monkeypatch.setattr(health, "psycopg", database)

    report = health.check_health("postgresql://example")

    assert report["ready"] is True
    assert database.executions[0] == (
        "SELECT set_config('statement_timeout', %s, true)",
        (str(health.HEALTH_STATEMENT_TIMEOUT_MILLISECONDS),),
    )
    assert database.executions[1] == (
        "SELECT component, is_ready, detail FROM pg_llm_batch_health_check()",
        None,
    )
    assert len(database.executions) == 2


def test_public_health_report_removes_diagnostic_details():
    """Public readiness evidence exposes state but never diagnostic text."""
    report = {
        "ready": False,
        "components": [
            {
                "component": "database",
                "is_ready": False,
                "detail": "password=super-secret host=db.internal.example",
                "debug": "provider-controlled-extra-field",
            },
            {
                "component": "pg_tiktoken",
                "is_ready": True,
                "detail": "extension version 1.2.3",
            },
        ],
        "internal": "must-not-cross-http-boundary",
    }

    public_report = health.public_health_report(report)

    assert public_report == {
        "ready": False,
        "components": [
            {"component": "database", "is_ready": False},
            {"component": "pg_tiktoken", "is_ready": True},
        ],
    }
    assert "super-secret" not in json.dumps(public_report)
    assert "db.internal.example" not in json.dumps(public_report)
    assert "provider-controlled-extra-field" not in json.dumps(public_report)


def test_public_health_report_fails_closed_on_coercive_readiness_values():
    """Malformed truthy readiness values cannot become public success evidence."""
    report = {
        "ready": "false",
        "components": [
            {"component": "database", "is_ready": "false", "detail": "secret"}
        ],
    }

    assert health.public_health_report(report) == {
        "ready": False,
        "components": [],
    }


def test_serve_healthz_reports_redacted_status_body_and_not_found(monkeypatch):
    """The HTTP wrapper emits only redacted readiness and a strict 404 elsewhere."""
    events = []
    bodies = []

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
            body = handler.wfile.getvalue()
            bodies.append((path, body))
            return body

        def serve_forever(self):
            assert self._request("/other") == b""
            assert self._request("/") == b""
            body = self._request("/healthz/")
            decoded = json.loads(body)
            assert decoded == {
                "ready": False,
                "components": [{"component": "database", "is_ready": False}],
            }
            assert b"super-secret" not in body
            assert b"db.internal.example" not in body
            handler = self.handler_class.__new__(self.handler_class)
            assert handler.log_message("ignored") is None

    monkeypatch.setattr("http.server.HTTPServer", FakeHTTPServer)
    monkeypatch.setattr(
        health,
        "check_health",
        lambda _dsn: {
            "ready": False,
            "components": [
                {
                    "component": "database",
                    "is_ready": False,
                    "detail": "password=super-secret host=db.internal.example",
                }
            ],
        },
    )
    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)
    assert ("address", ("127.0.0.1", 8090)) in events
    assert ("/other", "status", 404) in events
    assert ("/", "status", 404) in events
    assert ("/healthz/", "status", 503) in events
    assert ("/healthz/", "header", "Content-Type", "application/json") in events
    assert ("/healthz/", "header", "Cache-Control", "no-store") in events
    assert bodies[-1][0] == "/healthz/"


def test_serve_healthz_uses_sanitized_readiness_for_status(monkeypatch):
    """Malformed local readiness cannot produce an HTTP 200 by truth coercion."""
    events = []
    bodies = []

    class FakeHTTPServer:
        def __init__(self, _address, handler_class):
            self.handler_class = handler_class

        def serve_forever(self):
            handler = self.handler_class.__new__(self.handler_class)
            handler.path = "/healthz"
            handler.wfile = io.BytesIO()
            handler.send_response = lambda status: events.append(status)
            handler.send_header = lambda *_args: None
            handler.end_headers = lambda: None
            handler.do_GET()
            bodies.append(json.loads(handler.wfile.getvalue()))

    monkeypatch.setattr("http.server.HTTPServer", FakeHTTPServer)
    monkeypatch.setattr(
        health,
        "check_health",
        lambda _dsn: {
            "ready": "false",
            "components": [{"component": "database", "is_ready": "false"}],
        },
    )

    health.serve_healthz("postgresql://example")

    assert events == [503]
    assert bodies == [{"ready": False, "components": []}]
