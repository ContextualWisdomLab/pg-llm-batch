# SPDX-License-Identifier: Apache-2.0
"""Secure-default network binding contracts for readiness serving."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from pg_llm_batch import cli, health


_ROOT = Path(__file__).resolve().parents[1]


def test_serve_healthz_cli_defaults_to_loopback() -> None:
    """A direct CLI invocation must not listen on every interface by default."""
    args = cli.build_parser().parse_args(
        ["serve-healthz", "--dsn", "postgresql://example"]
    )

    assert args.host == "127.0.0.1"


def test_serve_healthz_library_api_defaults_to_loopback() -> None:
    """Direct library callers must receive the same secure listener default."""
    signature = inspect.signature(health.serve_healthz)

    assert signature.parameters["host"].default == "127.0.0.1"


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
    """The executable container command must opt in to all-interface binding."""
    lines = (_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    cmd_lines = [line.strip() for line in lines if line.lstrip().startswith("CMD ")]

    assert len(cmd_lines) == 1
    command = json.loads(cmd_lines[0].removeprefix("CMD "))
    assert command == [
        "sh",
        "-c",
        "python -m pg_llm_batch serve-healthz --host 0.0.0.0 "
        "--port ${PG_LLM_BATCH_HEALTH_PORT}",
    ]
