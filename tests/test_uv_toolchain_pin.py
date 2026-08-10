# SPDX-License-Identifier: Apache-2.0
"""Regression contract for the repository uv toolchain version."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UV_CONFIG = ROOT / "uv.toml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
EXPECTED_REQUIRED_VERSION = 'required-version = "==0.12.3"'


def test_uv_toolchain_version_is_exactly_pinned() -> None:
    """CI must not resolve a different uv release merely because time passed."""
    assert UV_CONFIG.exists(), "missing root uv.toml toolchain authority"

    substantive_lines = [
        line.strip()
        for line in UV_CONFIG.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert substantive_lines == [EXPECTED_REQUIRED_VERSION]


def test_ci_uses_setup_uv_without_an_explicit_latest_override() -> None:
    """The workflow must allow setup-uv to resolve the exact root requirement."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "astral-sh/setup-uv@" in workflow
    assert 'version: "latest"' not in workflow
    assert "version: latest" not in workflow
