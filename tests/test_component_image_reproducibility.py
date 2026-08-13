# SPDX-License-Identifier: Apache-2.0
"""Regression tests for deterministic component-image package inputs."""

from __future__ import annotations

import re
from pathlib import Path

from tests.dockerfile_contract import dockerfile_uses_apt_get_upgrade


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATTERN = re.compile(
    r"snapshot\.debian\.org/archive/debian(?:-security)?/"
    r"(?P<timestamp>20\d{6}T\d{6}Z)"
)


def test_component_image_does_not_perform_distribution_upgrade() -> None:
    """Ordinary image builds must not float the whole Debian package set."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert not dockerfile_uses_apt_get_upgrade(dockerfile)


def test_upgrade_detection_handles_options_and_line_continuations() -> None:
    """Formatting and apt-get options must not bypass the upgrade prohibition."""
    upgrade_commands = (
        "RUN apt-get --assume-yes upgrade\n",
        "RUN apt-get \\\n    -o Dpkg::Options::=--force-confold \\\n    upgrade\n",
    )

    assert all(dockerfile_uses_apt_get_upgrade(command) for command in upgrade_commands)
    assert not dockerfile_uses_apt_get_upgrade(
        "RUN apt-get update && apt-get install --yes curl\n"
    )


def test_component_image_uses_one_fixed_debian_snapshot() -> None:
    """Runtime packages resolve from one immutable Debian snapshot timestamp."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    matches = list(SNAPSHOT_PATTERN.finditer(dockerfile))

    assert len(matches) >= 2
    assert len({match.group("timestamp") for match in matches}) == 1
    assert "check-valid-until=no" in dockerfile.lower()
    assert "deb.debian.org" not in dockerfile
    assert "security.debian.org" not in dockerfile


def test_component_image_preserves_minimal_runtime_packages() -> None:
    """Snapshot hardening retains PostgreSQL client and health-probe packages."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"apt-get install[^\n]*\blibpq5\b", dockerfile)
    assert re.search(r"apt-get install[^\n]*\bcurl\b", dockerfile)
