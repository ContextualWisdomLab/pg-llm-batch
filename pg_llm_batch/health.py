# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Readiness checks for the standalone service and Docker healthcheck.

``check_health`` runs the ``pg_llm_batch_health_check()`` SQL function and
reports per-component readiness. ``serve_healthz`` exposes it over HTTP at
``/healthz`` (200 when ready, 503 otherwise) so docker-compose can gate on it.
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
    """Return a readiness report ``{ready: bool, components: [...]}``."""
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
                            "is_ready": is_ready if type(is_ready) is bool else False,
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
    """Return readiness using only fixed component names and boolean states."""
    public_components: List[Dict[str, Any]] = []
    observed_components = set()
    for component in report.get("components", []):
        component_name = component.get("component")
        if component_name not in REQUIRED_COMPONENTS:
            continue
        if component_name in observed_components:
            return {"ready": False, "components": []}
        observed_components.add(component_name)
        public_components.append(
            {
                "component": component_name,
                "is_ready": component.get("is_ready") is True,
            }
        )
    required_states = {
        component["component"]: component["is_ready"] for component in public_components
    }
    required_ready = set(required_states) == REQUIRED_COMPONENTS and all(
        required_states.values()
    )
    return {
        "ready": report.get("ready") is True and required_ready,
        "components": public_components,
    }


def serve_healthz(dsn: str, host: str = "0.0.0.0", port: int = 8080) -> None:
    """Serve a minimal ``/healthz`` endpoint (blocking)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        """HTTP request handler that answers ``/healthz`` with the readiness report."""

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            """Return the readiness report for ``/healthz``, or 404 for other paths."""
            if self.path.rstrip("/") not in ("/healthz", ""):
                self.send_response(404)
                self.end_headers()
                return
            report = check_health(dsn)
            body = json.dumps(report).encode("utf-8")
            self.send_response(200 if report["ready"] else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:  # silence access logs
            """Suppress the default stderr access logging."""
            return

    server = HTTPServer((host, port), _Handler)
    logger.info("Serving /healthz on %s:%s", host, port)
    server.serve_forever()
