# SPDX-License-Identifier: Apache-2.0
"""Contracts for autonomous-maintenance scheduler failure recovery documentation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_ADR = ROOT / "docs/automation/ADR-0006-scheduler-failure-recovery.md"
ADR_INDEX = ROOT / "docs/adr/README.md"
OPERABILITY = ROOT / "docs/OPERABILITY.md"
TRACEABILITY = ROOT / "docs/TRACEABILITY.md"
FITNESS = ROOT / "docs/DOCUMENTATION_FITNESS.md"


def _normalized(path: Path) -> str:
    """Return normalized lower-case Markdown for semantic contract assertions."""
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_scheduler_failure_recovery_is_canonical_and_work_conserving() -> None:
    """Generic scheduler failures must become bounded control-plane recovery work."""
    assert SCHEDULER_ADR.exists(), "missing canonical scheduler-failure recovery ADR"

    adr = _normalized(SCHEDULER_ADR)
    index = _normalized(ADR_INDEX)
    operability = _normalized(OPERABILITY)
    traceability = _normalized(TRACEABILITY)
    fitness = _normalized(FITNESS)

    assert "](../automation/adr-0006-scheduler-failure-recovery.md)" in index

    for phrase in (
        "generic scheduled-task failure",
        "control-plane incident",
        "repository failure",
        "enabled hourly task",
        "do not create a duplicate scheduler",
        "prompt size",
        "same invocation",
        "double exit sweep",
        "rollback",
        "supersession",
    ):
        assert phrase in adr, phrase

    assert "scheduler/control-plane failure" in operability
    assert "repository failure" in operability
    assert "same invocation" in operability
    assert "do not create a duplicate scheduler" in operability

    assert "scheduler failure recovery" in traceability
    assert "adr-0006-scheduler-failure-recovery.md" in traceability
    assert "scheduler failure recovery" in fitness
    assert "present-current" in fitness
