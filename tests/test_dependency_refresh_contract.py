# SPDX-License-Identifier: Apache-2.0
"""Contract tests for immutable, cost-bounded dependency refreshes."""

from __future__ import annotations

from pathlib import Path


def test_ci_uses_reviewed_action_commits_and_explicit_cache_pruning() -> None:
    """CI pins reviewed actions, uv, and the cache-cost policy."""
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in workflow
    assert workflow.count('version: "0.12.1"') == 2
    assert workflow.count("prune-cache: true") == 2


def test_container_build_inputs_use_reviewed_immutable_digests() -> None:
    """Both deployable build graphs use the consolidated immutable digests."""
    component = Path("Dockerfile").read_text(encoding="utf-8")
    postgres = Path("docker/postgres/Dockerfile").read_text(encoding="utf-8")
    assert component.count("sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6") == 2
    assert "sha256:99e09cb2284e2ddbb73a995deee3e91783fd04d177602ccf6eab326d778ee777" in postgres


def test_ruff_patch_release_is_locked_in_project_and_lockfile() -> None:
    """The lint tool update is represented consistently in both lock sources."""
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    lockfile = Path("uv.lock").read_text(encoding="utf-8")
    assert '"ruff==0.16.1"' in project
    assert 'name = "ruff"\nversion = "0.16.1"' in lockfile
