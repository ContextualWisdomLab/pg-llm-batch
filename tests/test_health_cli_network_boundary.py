# SPDX-License-Identifier: Apache-2.0
"""Secure-default network binding contracts for the readiness CLI."""

from __future__ import annotations

from pg_llm_batch import cli


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
