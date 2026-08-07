# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Readiness checks for the standalone service and Docker healthcheck.

``check_health`` runs the ``pg_llm_batch_health_check()`` SQL function and keeps
per-component diagnostic detail for local operator use. ``serve_healthz``
projects that report to a minimal HTTP-safe representation before serving
``/healthz`` (200 when ready, 503 otherwise), so probe clients never receive
connection exceptions or database diagnostic text.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

try:  # pragma: no cover - optional dependency
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore

logger = logging.getLogger(__name__)

# Components that must be ready for the service to be considered healthy.
REQUIRED_COMPONENTS = {"database", "pg_tiktoken", "com_config"}


def check_health(dsn: str) -> Dict[str, Any]:
    """Return a detailed local readiness report for operators and the CLI."""
    if psycopg is None:
        return {
            "ready": False,
            "components": [
                {"component": "psycopg", "is_ready": False, "detail": "not installed"}
            ],
        }
    components: List[Dict[str, Any]] = []
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT component, is_ready, detail FROM pg_llm_batch_health_check()"
                )
                for component, is_ready, detail in cur.fetchall():
                    components.append(
                        {
                            "component": component,
                            "is_ready": bool(is_ready),
                            "detail": detail,
                        }
                    )
    except Exception as exc:
        return {
            "ready": False,
            "components": [
                {"component": "database", "is_ready": False, "detail": str(exc)}
            ],
        }

    observed = {c["component"] for c in components}
    missing = sorted(REQUIRED_COMPONENTS - observed)
    for component in missing:
        components.append(
            {
                "component": component,
                "is_ready": False,
                "detail": "missing from pg_llm_batch_health_check() result",
            }
        )
    if missing:
        logger.warning("Health check omitted required components: %s", ", ".join(missing))

    ready = not missing and all(
        c["is_ready"]
        for c in components
        if c["component"] in REQUIRED_COMPONENTS
    )
    return {"ready": ready, "components": components}


def public_health_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return the HTTP-safe readiness projection without diagnostic details.

    Local callers can keep using :func:`check_health` when they need the
    database-provided ``detail`` field. Probe clients only need the overall
    readiness decision and each component's boolean state, so this projection
    deliberately copies only those fixed fields and drops every other key.
    """
    return {
        "ready": bool(report["ready"]),
        "components": [
            {
                "component": component["component"],
                "is_ready": bool(component["is_ready"]),
            }
            for component in report["components"]
        ],
    }


def serve_healthz(dsn: str, host: str = "0.0.0.0", port: int = 8080) -> None:
    """Serve a redacted ``/healthz`` readiness endpoint (blocking)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        """HTTP request handler that answers ``/healthz`` with redacted readiness."""

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            """Return redacted readiness for ``/healthz``, or 404 elsewhere."""
            if self.path.rstrip("/") not in ("/healthz", ""):
                self.send_response(404)
                self.end_headers()
                return
            report = check_health(dsn)
            body = json.dumps(public_health_report(report)).encode("utf-8")
            self.send_response(200 if report["ready"] else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:  # silence access logs
            """Suppress the default stderr access logging."""
            return

    server = HTTPServer((host, port), _Handler)
    logger.info("Serving /healthz on %s:%s", host, port)
    server.serve_forever()