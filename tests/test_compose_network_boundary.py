# SPDX-License-Identifier: Apache-2.0
"""Security contracts for standalone Docker Compose host publishing."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE_PATH = _ROOT / "docker-compose.yml"


def _compose_model() -> dict[str, Any]:
    """Return Docker Compose's normalized JSON model for the standalone stack."""
    docker = shutil.which("docker")
    assert docker is not None, "Docker CLI is required to validate Compose security"
    result = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(_COMPOSE_PATH),
            "config",
            "--format",
            "json",
        ],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    model = json.loads(result.stdout)
    assert isinstance(model, dict)
    return model


def _assert_only_loopback_port(
    model: dict[str, Any], service_name: str, port_number: int
) -> None:
    """Require one exact IPv4-loopback TCP publication for a service port."""
    services = model.get("services")
    assert isinstance(services, dict)
    service = services.get(service_name)
    assert isinstance(service, dict)
    ports = service.get("ports")
    assert isinstance(ports, list)
    assert len(ports) == 1

    published = ports[0]
    assert isinstance(published, dict)
    assert published.get("host_ip") == "127.0.0.1"
    assert int(published.get("published")) == port_number
    assert published.get("target") == port_number
    assert published.get("protocol", "tcp") == "tcp"


def test_standalone_compose_publishes_database_and_health_only_on_loopback() -> None:
    """Canonical Compose ports must expose only the two intended loopback sockets."""
    model = _compose_model()

    _assert_only_loopback_port(model, "postgres", 5432)
    _assert_only_loopback_port(model, "component", 8080)
