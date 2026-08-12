# SPDX-License-Identifier: Apache-2.0
"""Supply-chain contract for Dependabot-managed uv lock updates."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dependabot_uses_uv_ecosystem_for_python_lock_updates() -> None:
    """Python dependency PRs must be able to update pyproject.toml and uv.lock."""
    config = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    assert 'package-ecosystem: "uv"' in config
    assert 'package-ecosystem: "pip"' not in config
    assert (ROOT / "pyproject.toml").is_file()
    assert (ROOT / "uv.lock").is_file()
