# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the public readiness confidentiality boundary."""

from __future__ import annotations

import io
import json

from pg_llm_batch import health


def test_healthz_exposes_only_public_readiness_projection(monkeypatch) -> None:
    """Keep operator/database detail and unknown component names out of HTTP."""
    secret = "postgresql://operator:secret@example.internal/db"
    internal_report = {
        "ready": False,
        "components": [
            {"component": "database", "is_ready": False, "detail": secret},
            {"component": "pg_tiktoken", "is_ready": True, "detail": "installed"},
            {"component": "com_config", "is_ready": True, "detail": "ready"},
            {
                "component": "provider_internal_probe",
                "is_ready": False,
                "detail": "private topology detail",
            },
        ],
    }
    observed: dict[str, object] = {}

    class FakeHTTPServer:
        def __init__(self, _address, handler_class):
            self.handler_class = handler_class

        def serve_forever(self) -> None:
            handler = self.handler_class.__new__(self.handler_class)
            handler.path = "/healthz"
            handler.wfile = io.BytesIO()
            handler.send_response = lambda status: observed.update(status=status)
            handler.send_header = lambda _key, _value: None
            handler.end_headers = lambda: None
            handler.do_GET()
            observed["body"] = handler.wfile.getvalue()

    monkeypatch.setattr("http.server.HTTPServer", FakeHTTPServer)
    monkeypatch.setattr(health, "check_health", lambda _dsn: internal_report)

    health.serve_healthz("postgresql://example", host="127.0.0.1", port=8090)

    body = observed["body"]
    assert isinstance(body, bytes)
    decoded = json.loads(body)
    assert observed["status"] == 503
    assert secret.encode() not in body
    assert b"detail" not in body
    assert b"provider_internal_probe" not in body
    assert decoded == {
        "ready": False,
        "components": [
            {"component": "database", "is_ready": False},
            {"component": "pg_tiktoken", "is_ready": True},
            {"component": "com_config", "is_ready": True},
        ],
    }
