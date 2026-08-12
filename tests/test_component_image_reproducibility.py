# SPDX-License-Identifier: Apache-2.0
"""Regression tests for deterministic component-image package inputs."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_component_image_does_not_perform_distribution_upgrade() -> None:
    """Ordinary image builds must not float the whole Debian package set."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "apt-get upgrade" not in dockerfile
