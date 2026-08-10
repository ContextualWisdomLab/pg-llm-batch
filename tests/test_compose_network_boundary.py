# SPDX-License-Identifier: Apache-2.0
"""Security contracts for standalone Docker Compose host publishing."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest


_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE_PATH = _ROOT / "docker-compose.yml"
_EXPECTED_PUBLISHED_PORTS = {"postgres": 5432, "component": 8080}


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


def _assert_standalone_port_contract(model: dict[str, Any]) -> None:
    """Require exactly the reviewed database and health host publications."""
    services = model.get("services")
    assert isinstance(services, dict)

    published_services: set[str] = set()
    for service_name, service in services.items():
        assert isinstance(service_name, str)
        assert isinstance(service, dict)
        ports = service.get("ports")
        if ports is None:
            continue
        assert isinstance(ports, list)
        if ports:
            published_services.add(service_name)

    assert published_services == set(_EXPECTED_PUBLISHED_PORTS)
    for service_name, port_number in _EXPECTED_PUBLISHED_PORTS.items():
        _assert_only_loopback_port(model, service_name, port_number)


def test_standalone_compose_publishes_database_and_health_only_on_loopback() -> None:
    """Canonical Compose ports must expose only the two intended loopback sockets."""
    _assert_standalone_port_contract(_compose_model())


def test_standalone_compose_does_not_override_legacy_health_port_environment() -> None:
    """The standalone profile must not advertise an inert shell-era health-port knob."""
    model = _compose_model()
    services = model.get("services")
    assert isinstance(services, dict)
    component = services.get("component")
    assert isinstance(component, dict)
    environment = component.get("environment")
    assert isinstance(environment, dict)

    assert "PG_LLM_BATCH_HEALTH_PORT" not in environment


def test_standalone_port_contract_rejects_an_unexpected_published_service() -> None:
    """Adding another host-published service must fail the standalone boundary."""
    model: dict[str, Any] = {
        "services": {
            "postgres": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "5432",
                        "target": 5432,
                        "protocol": "tcp",
                    }
                ]
            },
            "component": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "8080",
                        "target": 8080,
                        "protocol": "tcp",
                    }
                ]
            },
            "rogue": {
                "ports": [
                    {
                        "host_ip": "0.0.0.0",
                        "published": "9090",
                        "target": 9090,
                        "protocol": "tcp",
                    }
                ]
            },
        }
    }

    with pytest.raises(AssertionError):
        _assert_standalone_port_contract(model)
