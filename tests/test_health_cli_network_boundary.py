# SPDX-License-Identifier: Apache-2.0
"""Secure-default network binding contracts for the readiness CLI."""

from __future__ import annotations

from pathlib import Path

from pg_llm_batch import cli


_ROOT = Path(__file__).resolve().parents[1]


def test_serve_healthz_cli_defaults_to_loopback() -> None:
    """A direct host invocation must not listen on every interface by default."""
    args = cli.build_parser().parse_args(
        ["serve-healthz", "--dsn", "postgresql://example"]
    )

    assert args.host == "127.0.0.1"


def test_serve_healthz_cli_allows_explicit_container_binding() -> None:
    """Container entrypoints may still explicitly request all-interface binding."""
    args = cli.build_parser().parse_args(
        [
            "serve-healthz",
            "--dsn",
            "postgresql://example",
            "--host",
            "0.0.0.0",
        ]
    )

    assert args.host == "0.0.0.0"


def test_component_image_explicitly_requests_container_wide_binding() -> None:
    """The bundled container must opt in to all-interface binding explicitly."""
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "serve-healthz --host 0.0.0.0 --port ${PG_LLM_BATCH_HEALTH_PORT}" in dockerfile
