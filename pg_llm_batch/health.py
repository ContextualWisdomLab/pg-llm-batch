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

# Bound the database-side readiness statement independently of connection
# acquisition. This is transaction-local and does not alter server defaults.
HEALTH_STATEMENT_TIMEOUT_MILLISECONDS = 4_000

# The standalone listener intentionally uses one thread per admitted request,
# so cap admission before allocating another thread or database connection.
HEALTH_MAX_CONCURRENT_REQUESTS = 32


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
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(HEALTH_STATEMENT_TIMEOUT_MILLISECONDS),),
                )
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

    required_states: Dict[str, bool] = {}
    duplicate_required = set()
    for component in components:
        component_name = component["component"]
        if component_name not in REQUIRED_COMPONENTS:
            continue
        if component_name in required_states:
            duplicate_required.add(component_name)
            continue
        required_states[component_name] = component["is_ready"]

    missing = sorted(REQUIRED_COMPONENTS - set(required_states))
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
    if duplicate_required:
        logger.warning(
            "Health check duplicated required components: %s",
            ", ".join(sorted(duplicate_required)),
        )

    ready = (
        not missing
        and not duplicate_required
        and all(required_states.values())
    )
    return {"ready": ready, "components": components}


def _not_ready_public_health_report() -> Dict[str, Any]:
    """Return the fixed fail-closed public representation for malformed input."""
    return {"ready": False, "components": []}


def public_health_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return the HTTP-safe readiness projection without diagnostic details.

    Local callers can keep using :func:`check_health` when they need the
    database-provided ``detail`` field. Probe clients only need the overall
    readiness decision and the fixed required components' boolean states. This
    projection therefore accepts only exact boolean readiness fields and string
    component names, exposes only names in :data:`REQUIRED_COMPONENTS`, and
    fails closed on malformed shapes or contradictory required-component
    evidence.
    """
    ready = report.get("ready")
    components = report.get("components")
    if type(ready) is not bool or type(components) is not list:
        return _not_ready_public_health_report()

    public_components: List[Dict[str, Any]] = []
    required_states: Dict[str, bool] = {}
    for component in components:
        if type(component) is not dict:
            return _not_ready_public_health_report()
        component_name = component.get("component")
        is_ready = component.get("is_ready")
        if type(component_name) is not str:
            return _not_ready_public_health_report()
        if type(is_ready) is not bool:
            return _not_ready_public_health_report()
        if component_name not in REQUIRED_COMPONENTS:
            continue
        if component_name in required_states:
            return _not_ready_public_health_report()
        required_states[component_name] = is_ready
        public_components.append(
            {"component": component_name, "is_ready": is_ready}
        )

    required_ready = (
        set(required_states) == REQUIRED_COMPONENTS
        and all(required_states.values())
    )
    return {"ready": ready and required_ready, "components": public_components}


def serve_healthz(dsn: str, host: str = "0.0.0.0", port: int = 8080) -> None:
    """Serve a redacted ``/healthz`` readiness endpoint (blocking)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    from threading import BoundedSemaphore

    class _ThreadingHealthHTTPServer(ThreadingMixIn, HTTPServer):
        """Handle a bounded number of independent daemon probe threads."""

        daemon_threads = True
        _request_slots = BoundedSemaphore(HEALTH_MAX_CONCURRENT_REQUESTS)

        def process_request(self, request: Any, client_address: Any) -> None:
            """Admit a request only when one bounded worker slot is available."""
            if not self._request_slots.acquire(blocking=False):
                logger.warning("Rejecting readiness connection: concurrency limit reached")
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self._request_slots.release()
                raise

        def process_request_thread(self, request: Any, client_address: Any) -> None:
            """Release one admission slot after the request thread terminates."""
            try:
                super().process_request_thread(request, client_address)
            finally:
                self._request_slots.release()

    class _Handler(BaseHTTPRequestHandler):
        """HTTP request handler that answers ``/healthz`` with redacted readiness."""

        def send_response(self, code: int, message: str | None = None) -> None:
            """Send status metadata without exposing the stdlib/Python fingerprint."""
            self.log_request(code)
            self.send_response_only(code, message)
            self.send_header("Date", self.date_time_string())

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            """Return redacted readiness for ``/healthz``, or 404 elsewhere."""
            if self.path.rstrip("/") != "/healthz":
                self.send_response(404)
                self.end_headers()
                return
            report = check_health(dsn)
            public_report = public_health_report(report)
            body = json.dumps(public_report).encode("utf-8")
            self.send_response(200 if public_report["ready"] else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:  # silence access logs
            """Suppress the default stderr access logging."""
            return

    server = _ThreadingHealthHTTPServer((host, port), _Handler)
    logger.info("Serving /healthz on %s:%s", host, port)
    server.serve_forever()
