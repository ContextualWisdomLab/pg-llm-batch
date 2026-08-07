# SPDX-License-Identifier: Apache-2.0
"""Contract tests for immutable, cost-bounded dependency refreshes."""

from __future__ import annotations

from pathlib import Path


def _mapping_blocks(source: str, key: str, indent: int) -> tuple[str, ...]:
    """Return exact YAML-like mapping blocks at one indentation level."""
    lines = source.splitlines()
    marker = f"{' ' * indent}{key}:"
    starts = [index for index, line in enumerate(lines) if line == marker]
    blocks: list[str] = []
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            line = lines[index]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent:
                end = index
                break
        blocks.append("\n".join(lines[start:end]))
    return tuple(blocks)


def _sequence_items(source: str, item_indent: int) -> tuple[str, ...]:
    """Split one YAML-like sequence into exact indentation-scoped items."""
    lines = source.splitlines()
    prefix = f"{' ' * item_indent}- "
    starts = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    items: list[str] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        items.append("\n".join(lines[start:end]))
    return tuple(items)


def _optional_scalar_value(source: str, key: str) -> str | None:
    """Read at most one scalar from a bounded step, excluding inline comments."""
    prefix = f"{key}:"
    matches = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].lstrip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            matches.append(value.split(" #", 1)[0].strip())
    assert len(matches) <= 1, f"expected at most one scalar {key!r} per step"
    return matches[0] if matches else None


def _workflow_steps(workflow: str) -> tuple[str, ...]:
    """Return every exact job-step item without crossing job boundaries."""
    steps: list[str] = []
    for steps_block in _mapping_blocks(workflow, "steps", 4):
        steps.extend(_sequence_items(steps_block, 6))
    return tuple(steps)


def test_ci_uses_reviewed_action_commits_and_explicit_cache_pruning() -> None:
    """Every uv setup step carries its own reviewed pin and cache controls."""
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    steps = _workflow_steps(workflow)
    uses_values = tuple(
        value
        for step in steps
        if (value := _optional_scalar_value(step, "uses")) is not None
    )

    assert "step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920" in uses_values
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in uses_values
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in uses_values

    setup_uv = "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9"
    setup_uv_steps = tuple(
        step for step in steps if _optional_scalar_value(step, "uses") == setup_uv
    )
    assert len(setup_uv_steps) >= 2
    for step in setup_uv_steps:
        assert _optional_scalar_value(step, "version") == '"0.12.1"'
        assert _optional_scalar_value(step, "prune-cache") == "true"


def test_setup_uv_controls_cannot_be_borrowed_from_a_sibling_step() -> None:
    """A uv step without local controls remains invalid despite nearby decoys."""
    workflow = """jobs:
  example:
    steps:
      - uses: astral-sh/setup-uv@reviewed-pin
      - name: Decoy values
        version: "0.12.1"
        prune-cache: true
"""
    steps = _workflow_steps(workflow)
    setup_step = next(
        step
        for step in steps
        if _optional_scalar_value(step, "uses")
        == "astral-sh/setup-uv@reviewed-pin"
    )
    assert _optional_scalar_value(setup_step, "version") is None
    assert _optional_scalar_value(setup_step, "prune-cache") is None


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
