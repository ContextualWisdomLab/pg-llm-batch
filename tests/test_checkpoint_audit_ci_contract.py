# SPDX-License-Identifier: Apache-2.0
"""CI contract for the live checkpoint-audit PostgreSQL verification gate."""

from __future__ import annotations

from pathlib import Path


def _mapping_blocks(source: str, key: str, indent: int) -> tuple[str, ...]:
    """Return exact YAML-like mapping blocks at one reviewed indentation level."""
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


def _single_mapping_block(source: str, key: str, indent: int) -> str:
    """Return one uniquely named mapping block or fail the contract."""
    blocks = _mapping_blocks(source, key, indent)
    assert len(blocks) == 1, f"expected one {key!r} block at indent {indent}"
    return blocks[0]


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


def _scalar_value(source: str, key: str) -> str:
    """Read one scalar from an already bounded block, excluding inline comments."""
    prefix = f"{key}:"
    matches = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            matches.append(value.split(" #", 1)[0].strip())
    assert len(matches) == 1, f"expected one scalar {key!r} in bounded block"
    return matches[0]


def _single_step_with_scalar(
    steps: tuple[str, ...],
    key: str,
    expected: str,
) -> str:
    """Return the only step whose reviewed scalar equals the expected value."""
    matches = []
    for step in steps:
        try:
            value = _scalar_value(step, key)
        except AssertionError:
            continue
        if value == expected:
            matches.append(step)
    assert len(matches) == 1, f"expected one step with {key}: {expected}"
    return matches[0]


def test_ci_runs_checkpoint_audit_against_ephemeral_postgres() -> None:
    """The exact audit job must bind every required service and step setting."""
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    ).read_text(encoding="utf-8")
    job = _single_mapping_block(workflow, "checkpoint-audit-integration", 2)
    postgres = _single_mapping_block(job, "postgres", 6)
    job_environment = _single_mapping_block(job, "env", 4)
    steps = _sequence_items(_single_mapping_block(job, "steps", 4), 6)

    assert (
        _scalar_value(postgres, "image")
        == "postgres:16-bookworm@sha256:da788743d2060767375896de4d646f7576f5911461444b372616f19ea61db2ec"
    )
    assert (
        _scalar_value(job_environment, "PG_LLM_BATCH_TEST_DSN")
        == "postgresql://postgres:postgres@localhost:5432/postgres"
    )

    checkout = _single_step_with_scalar(
        steps,
        "uses",
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    )
    assert _scalar_value(checkout, "persist-credentials") == "false"

    integration = _single_step_with_scalar(
        steps,
        "name",
        "Run live checkpoint audit integration",
    )
    assert (
        _scalar_value(integration, "run")
        == "uv run pytest -q tests/test_checkpoint_audit_integration.py -m integration"
    )


def test_ci_scope_parser_excludes_settings_from_other_jobs() -> None:
    """A decoy outside the audit job cannot satisfy its bounded contract."""
    workflow = """jobs:
  decoy:
    env:
      PG_LLM_BATCH_TEST_DSN: reviewed-dsn
    steps:
      - name: Run live checkpoint audit integration
        run: reviewed-command
  checkpoint-audit-integration:
    services:
      postgres:
        image: unreviewed-image
    env:
      PG_LLM_BATCH_TEST_DSN: unreviewed-dsn
    steps:
      - name: Run live checkpoint audit integration
        run: unreviewed-command
"""
    job = _single_mapping_block(workflow, "checkpoint-audit-integration", 2)
    assert "reviewed-dsn" not in job
    assert "reviewed-command" not in job
    assert _scalar_value(_single_mapping_block(job, "postgres", 6), "image") == (
        "unreviewed-image"
    )
