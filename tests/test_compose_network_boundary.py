# SPDX-License-Identifier: Apache-2.0
"""Security contracts for standalone Docker Compose host publishing."""

from __future__ import annotations

from pathlib import Path


_COMPOSE_PATH = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_standalone_compose_publishes_database_and_health_only_on_loopback() -> None:
    """Default standalone ports must not listen on every host network interface."""
    compose = _COMPOSE_PATH.read_text(encoding="utf-8")

    assert '"127.0.0.1:5432:5432"' in compose
    assert '"127.0.0.1:8080:8080"' in compose
    assert '\n      - "5432:5432"' not in compose
    assert '\n      - "8080:8080"' not in compose
