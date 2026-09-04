# SPDX-License-Identifier: Apache-2.0
"""Contract tests for immutable, cost-bounded dependency refreshes."""

from __future__ import annotations

import re
from pathlib import Path


def _assert_action_uses_immutable_commits(workflow: str, action: str) -> None:
    """Require every reference to one reviewed action to use a full commit SHA."""
    references = re.findall(rf"{re.escape(action)}@([^\s]+)", workflow)
    assert references, f"{action} must remain present in CI"
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in references)


def test_ci_uses_reviewed_action_commits_and_explicit_cache_pruning() -> None:
    """CI uses immutable action revisions and preserves the cache-cost policy."""
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    for action in (
        "step-security/harden-runner",
        "actions/checkout",
        "actions/setup-python",
        "astral-sh/setup-uv",
    ):
        _assert_action_uses_immutable_commits(workflow, action)
    assert workflow.count("prune-cache: true") == 2


def test_container_build_inputs_use_reviewed_immutable_digests() -> None:
    """Both deployable build graphs use the consolidated immutable digests."""
    component = Path("Dockerfile").read_text(encoding="utf-8")
    postgres = Path("docker/postgres/Dockerfile").read_text(encoding="utf-8")
    assert component.count("sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6") == 2
    assert (
        "FROM rust:1.98-slim-bookworm@"
        "sha256:1469a27c125cb5a3aebfa4f4e4665d935b02fb72cc093b2c974b3d740e43f157 "
        "AS rust-toolchain"
    ) in postgres


def test_ruff_patch_release_is_locked_in_project_and_lockfile() -> None:
    """The lint tool update is represented consistently in both lock sources."""
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    lockfile = Path("uv.lock").read_text(encoding="utf-8")
    assert '"ruff==0.16.1"' in project
    assert 'name = "ruff"\nversion = "0.16.1"' in lockfile