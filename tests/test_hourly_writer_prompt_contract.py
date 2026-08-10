# SPDX-License-Identifier: Apache-2.0
"""Contracts for the compact pg-llm-batch hourly writer prompt source."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "docs/automation/HOURLY_WRITER_PROMPT.md"
SCHEDULER_ADR = ROOT / "docs/automation/ADR-0006-scheduler-failure-recovery.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"
MAX_PROMPT_BYTES = 8_000
FULL_SHA = re.compile(r"\b[0-9a-f]{40}\b")


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_hourly_writer_prompt_is_compact_current_and_work_conserving() -> None:
    """The scheduler source must stay concise and delegate product truth to GitHub."""
    assert PROMPT.exists(), "missing compact hourly writer prompt source"

    raw = PROMPT.read_text(encoding="utf-8")
    normalized = " ".join(raw.lower().split())

    assert len(raw.encode("utf-8")) <= MAX_PROMPT_BYTES
    assert FULL_SHA.search(raw.lower()) is None, "prompt must not pin transient commit evidence"

    for phrase in (
        "execution-first",
        "write only contextualwisdomlab/pg-llm-batch",
        "repository canonical documents",
        "fresh live queue",
        "exact current head sha",
        "exact live base tip sha",
        "waiting is local",
        "root-cause analysis",
        "practical feasibility",
        "prompt repair is intermediate",
        "material safe repository action",
        "two consecutive fresh exit sweeps",
        "nvidia_nim_api_key",
        "never copilot_github_token",
    ):
        assert phrase in normalized, phrase


def test_hourly_writer_prompt_preserves_merge_and_writer_authority() -> None:
    """The compact prompt must not lose exact evidence or single-writer gates."""
    normalized = _normalized(PROMPT)

    for phrase in (
        "hard writer lease",
        "independent non-author formal approval where required",
        "never bypass",
        "queued, pending, cancelled",
        "stack dependency order",
        "100% owned production statement and branch coverage",
        "active-pr behavior is not shipped",
    ):
        assert phrase in normalized, phrase


def test_hourly_writer_prompt_is_discoverable_from_canonical_governance() -> None:
    """Operators must find the compact prompt without chat or PR-body archaeology."""
    for document in (SCHEDULER_ADR, TRACEABILITY, FITNESS):
        normalized = _normalized(document)
        assert "hourly_writer_prompt.md" in normalized
        assert "compact hourly writer prompt" in normalized
