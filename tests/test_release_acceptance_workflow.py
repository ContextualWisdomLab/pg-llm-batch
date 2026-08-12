# SPDX-License-Identifier: Apache-2.0
"""Regression contract for the reproducible release acceptance workflow."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release-acceptance.yml"
UV_CONFIG = ROOT / "uv.toml"


def test_release_acceptance_workflow_is_exact_head_least_privilege() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read\n" in text
    assert "id-token: write" not in text
    assert "attestations: write" not in text
    assert "packages: write" not in text
    assert "persist-credentials: false" in text
    assert "ref: ${{ github.event.pull_request.head.sha }}" in text
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in text
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in text
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text


def test_release_acceptance_uv_matches_repository_toolchain_contract() -> None:
    """Release verification must install the exact uv version required by the repo."""
    text = WORKFLOW.read_text(encoding="utf-8")
    required_version = tomllib.loads(UV_CONFIG.read_text(encoding="utf-8"))[
        "required-version"
    ]

    assert required_version.startswith("==")
    exact_version = required_version.removeprefix("==")
    assert f'version: "{exact_version}"' in text


def test_release_acceptance_workflow_builds_twice_and_preserves_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "SOURCE_DATE_EPOCH" in text
    assert "git show -s --format=%ct HEAD" in text
    assert "uv build --no-sources --out-dir dist-first" in text
    assert "uv build --no-sources --out-dir dist-second" in text
    assert text.count("--no-create-gitignore") == 2
    assert "verify_reproducible_release" in text
    assert "write_release_manifest" in text
    assert "release-manifest.json" in text
    assert "retention-days: 14" in text


def test_release_acceptance_workflow_runs_for_every_packaged_input() -> None:
    """Every file class included in a distribution permanently triggers the gate."""
    text = WORKFLOW.read_text(encoding="utf-8")

    required_paths = (
        ".github/workflows/release-acceptance.yml",
        "pg_llm_batch/**",
        "tests/**",
        "docs/**",
        "docker/**",
        "AGENTS.md",
        "ARCHITECTURE.md",
        "CHANGELOG.md",
        "CLAUDE.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "README.md",
        "SECURITY.md",
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
        "NOTICE",
    )
    for path in required_paths:
        assert f"- {path}" in text
