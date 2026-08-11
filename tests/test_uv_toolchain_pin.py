# SPDX-License-Identifier: Apache-2.0
"""Regression contract for the repository uv toolchain version."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UV_CONFIG = ROOT / "uv.toml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
EXPECTED_REQUIRED_VERSION = 'required-version = "==0.12.3"'
_SETUP_UV_USES = "uses: astral-sh/setup-uv@"
_SETUP_UV_VERSION_INPUT = re.compile(r"(?m)^\s+(?:version|version-file):\s*")
_SETUP_UV_WORKING_DIRECTORY = re.compile(
    r"(?m)^\s+working-directory:\s*(?P<value>.+?)\s*$"
)
_ALLOWED_ROOT_WORKING_DIRECTORIES = {".", "${{ github.workspace }}"}


def _setup_uv_step_blocks(workflow: str) -> list[str]:
    """Return each complete setup-uv step without inspecting unrelated steps."""
    lines = workflow.splitlines()
    blocks: list[str] = []

    for uses_index, line in enumerate(lines):
        if _SETUP_UV_USES not in line:
            continue

        uses_indent = len(line) - len(line.lstrip())
        if line.lstrip().startswith("- uses:"):
            step_start = uses_index
        else:
            step_start = uses_index
            while step_start > 0:
                candidate = lines[step_start - 1]
                stripped = candidate.lstrip()
                indent = len(candidate) - len(stripped)
                if stripped.startswith("- ") and indent < uses_indent:
                    step_start -= 1
                    break
                step_start -= 1
            else:
                raise AssertionError("setup-uv use is not contained in a workflow step")

        step_indent = len(lines[step_start]) - len(lines[step_start].lstrip())
        step_end = len(lines)
        for index in range(uses_index + 1, len(lines)):
            candidate = lines[index]
            stripped = candidate.lstrip()
            indent = len(candidate) - len(stripped)
            if stripped.startswith("- ") and indent == step_indent:
                step_end = index
                break

        blocks.append("\n".join(lines[step_start:step_end]))

    return blocks


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
    """Every setup-uv step must defer version authority to the repository root."""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    setup_uv_steps = _setup_uv_step_blocks(workflow)

    assert len(setup_uv_steps) == 2, "unexpected setup-uv step count"
    for step in setup_uv_steps:
        assert _SETUP_UV_VERSION_INPUT.search(step) is None, step

        working_directory = _SETUP_UV_WORKING_DIRECTORY.search(step)
        if working_directory is not None:
            assert (
                working_directory.group("value").strip().strip('"\'')
                in _ALLOWED_ROOT_WORKING_DIRECTORIES
            ), step
