# SPDX-License-Identifier: Apache-2.0
"""Regression tests for deterministic component-image package inputs."""

from __future__ import annotations

from pathlib import Path

from tests.dockerfile_contract import dockerfile_uses_apt_get_upgrade


ROOT = Path(__file__).resolve().parents[1]


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
